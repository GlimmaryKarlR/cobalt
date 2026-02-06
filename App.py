import os
import time
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def background_worker(youtube_url, job_id):
    local_file = f"/tmp/{job_id}.mp4"
    start_time = time.time()
    
    try:
        with sync_playwright() as p:
            print(f"🧵 [Job {job_id[:8]}] Launching Browser (Native Mode)...")
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            # Update 1: Reaching the site
            supabase.table("jobs").update({"current_step": "Connecting to Downloader", "progress_percent": 15}).eq("id", job_id).execute()

            page.goto("https://downr.org", wait_until="networkidle", timeout=60000)
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            # Update 2: Waiting for Google Video Stream link
            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=60000)
            
            print(f"📡 [Job {job_id[:8]}] Stream found. Starting browser download...")
            
            # Update 3: The Download Trigger
            supabase.table("jobs").update({
                "current_step": "Downloading (This may take a few minutes...)", 
                "progress_percent": 40
            }).eq("id", job_id).execute()

            # Using expect_download to catch the browser's internal download event
            with page.expect_download(timeout=600000) as download_info:
                # Force the click via JS to ensure it bypasses any overlays
                page.eval_on_selector(download_selector, "el => el.click()")
            
            download = download_info.value
            
            # This is the 'blocking' part. It waits until the file is 100% saved to /tmp
            download.save_as(local_file)
            browser.close()

        # Update 4: Uploading to Supabase
        if os.path.exists(local_file):
            print(f"📤 [Job {job_id[:8]}] Uploading to Storage...")
            supabase.table("jobs").update({"current_step": "Finalizing Upload", "progress_percent": 85}).eq("id", job_id).execute()

            file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
            with open(local_file, "rb") as f:
                supabase.storage.from_("videos").upload(file_name, f)

            # Update 5: Success
            supabase.table("jobs").update({
                "video_url": f"videos/{file_name}",
                "status": "waiting", # Ready for Hugging Face
                "current_step": "Ready",
                "progress_percent": 100
            }).eq("id", job_id).execute()
            print(f"✅ [Job {job_id[:8]}] Success in {int(time.time() - start_time)}s")
            
    except Exception as e:
        print(f"❌ [Job {job_id[:8]}] Failed: {str(e)}")
        supabase.table("jobs").update({
            "status": "failed", 
            "error_message": f"Browser Error: {str(e)[:200]}"
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
            return jsonify({"error": "No URL"}), 400

        job_res = supabase.table("jobs").insert({
            "video_url": "pending", "status": "downloading", "progress_percent": 5,
            "current_step": "Initializing", "mode": "do", "tier_key": 1,
            "priority": "low", "source": "website"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(video_url, job_id)).start()
        
        return jsonify(job_res.data[0]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
