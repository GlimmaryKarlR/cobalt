import os
import time
import threading
import requests
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
    """Handles the heavy lifting with live MB tracking."""
    local_file = f"/tmp/{job_id}.mp4"
    try:
        with sync_playwright() as p:
            print(f"🧵 [Job {job_id[:8]}] Launching Browser...")
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context()
            page = context.new_page()

            # Step 1: Navigate to the bypass site
            supabase.table("jobs").update({"current_step": "Extracting Stream Link", "progress_percent": 15}).eq("id", job_id).execute()
            
            page.goto("https://downr.org", wait_until="networkidle", timeout=60000)
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            # Step 2: Extract the raw Google Video URL
            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=60000)
            direct_link = page.get_attribute(download_selector, "href")
            browser.close()

        if not direct_link:
            raise Exception("Could not extract direct stream link.")

        # Step 3: Streamed Download with MB Tracking
        print(f"📡 [Job {job_id[:8]}] Starting Streamed Download...")
        response = requests.get(direct_link, stream=True, timeout=30)
        total_size = int(response.headers.get('content-length', 0))
        bytes_downloaded = 0
        last_update_time = 0

        with open(local_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024): # 1MB chunks
                if chunk:
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    
                    # Update Supabase every 2 seconds to avoid rate limiting
                    if time.time() - last_update_time > 2:
                        mb_val = bytes_downloaded / (1024 * 1024)
                        # Calculate progress between 20% and 80%
                        calc_progress = 20 + int((bytes_downloaded / total_size) * 60) if total_size > 0 else 45
                        
                        supabase.table("jobs").update({
                            "current_step": f"Downloading ({mb_val:.1f} MB)",
                            "progress_percent": min(calc_progress, 80)
                        }).eq("id", job_id).execute()
                        last_update_time = time.time()

        # Step 4: Upload to Supabase Storage
        if os.path.exists(local_file):
            print(f"📤 [Job {job_id[:8]}] Uploading {os.path.getsize(local_file) // 1024}KB...")
            supabase.table("jobs").update({"current_step": "Finalizing Upload", "progress_percent": 85}).eq("id", job_id).execute()

            file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
            with open(local_file, "rb") as f:
                supabase.storage.from_("videos").upload(file_name, f, {"x-upsert": "true"})

            # Step 5: Finalize row
            supabase.table("jobs").update({
                "video_url": f"videos/{file_name}",
                "status": "waiting",
                "current_step": "Ready",
                "progress_percent": 100
            }).eq("id", job_id).execute()
            print(f"✅ [Job {job_id[:8]}] Success.")

    except Exception as e:
        error_msg = str(e)[:250]
        print(f"❌ [Job {job_id[:8]}] Error: {error_msg}")
        supabase.table("jobs").update({
            "status": "failed", 
            "error_message": f"Worker Error: {error_msg}"
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
            "video_url": "pending", 
            "status": "downloading",
            "progress_percent": 5,
            "current_step": "Initializing",
            "mode": "do", "tier_key": 1, "priority": "low", "source": "website"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(video_url, job_id)).start()

        return jsonify({
            "status": "success",
            "id": job_id,
            "job_id": job_id,
            "message": "Worker started"
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
