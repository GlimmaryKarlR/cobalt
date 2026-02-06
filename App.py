import os
import time
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

# Configuration
SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def background_worker(youtube_url, job_id):
    """Handles the download using Native Browser Stream to bypass CDN blocks."""
    local_file = f"/tmp/{job_id}.mp4"
    try:
        with sync_playwright() as p:
            print(f"🧵 [Job {job_id[:8]}] Launching Browser (Native Mode)...")
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            # accept_downloads=True is critical here
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            # Step 1: Navigate to the bypass site
            supabase.table("jobs").update({"current_step": "Connecting to Downloader", "progress_percent": 15}).eq("id", job_id).execute()
            
            page.goto("https://downr.org", wait_until="networkidle", timeout=60000)
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            # Step 2: Trigger the Native Browser Download
            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=60000)
            
            print(f"📡 [Job {job_id[:8]}] Stream found. Starting browser download...")
            supabase.table("jobs").update({
                "current_step": "Downloading (via Chromium Stream)", 
                "progress_percent": 45
            }).eq("id", job_id).execute()

            # Using expect_download to catch the browser's internal download event
            with page.expect_download(timeout=600000) as download_info:
                # Force the click via JS to bypass any UI overlays
                page.eval_on_selector(download_selector, "el => el.click()")
            
            download = download_info.value
            
            # This waits for the browser to finish writing the file to disk
            download.save_as(local_file)
            browser.close()

        # Step 3: Integrity Check
        file_size = os.path.getsize(local_file)
        if file_size < 1000000: # Files < 1MB are likely error pages/corrupt
             raise Exception(f"File too small ({file_size / 1024:.1f} KB). Download likely blocked.")

        # Step 4: Upload to Supabase Storage
        print(f"📤 [Job {job_id[:8]}] Uploading {file_size // 1024} KB...")
        supabase.table("jobs").update({"current_step": "Finalizing Upload", "progress_percent": 85}).eq("id", job_id).execute()

        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {
                "content-type": "video/mp4",
                "x-upsert": "true"
            })

        # Step 5: Success (Triggers Geometry Engine)
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()
        print(f"✅ [Job {job_id[:8]}] Success.")

    except Exception as e:
        error_msg = str(e)[:250]
        print(f"❌ [Job {job_id[:8]}] Failed: {error_msg}")
        supabase.table("jobs").update({
            "status": "failed", 
            "error_message": f"Browser Error: {error_msg}"
        }).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    try:
        data = request.get_json()
        video_url = data.get('url') or (data.get('record') and data.get('record').get('url'))
        
        if not video_url:
            return jsonify({"status": "error", "message": "No URL provided"}), 400

        job_res = supabase.table("jobs").insert({
            "video_url": "pending", "status": "downloading", "progress_percent": 5,
            "current_step": "Initializing", "mode": "do", "tier_key": 1, "source": "website"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(video_url, job_id)).start()

        return jsonify({"status": "success", "id": job_id, "job_id": job_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
