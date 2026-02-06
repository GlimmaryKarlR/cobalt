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
    local_file = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            # Step 1: Link Extraction
            supabase.table("jobs").update({"current_step": "Extracting Link", "progress_percent": 10}).eq("id", job_id).execute()
            page.goto("https://downr.org", wait_until="networkidle")
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            download_selector = "a[href*='googlevideo'], a:has-text('Download')"
            page.wait_for_selector(download_selector, timeout=60000)
            
            # Step 2: Set up Download Tracking
            with page.expect_download(timeout=300000) as download_info:
                page.click(download_selector, force=True)
            
            download = download_info.value
            local_file = f"/tmp/vid_{job_id[:8]}.mp4"

            # --- THE PERCENTAGE LOGIC ---
            print(f"📡 Download started for {job_id}")
            
            # Note: total_size can sometimes be -1 if the server doesn't provide it
            # But Google Video usually provides Content-Length
            
            # We poll the download status while it's in progress
            last_update = 0
            while not download.path(): # While file is still streaming to temp
                # You can't get partial bytes from Playwright easily, 
                # but we can track the 'current_step' to show we are moving.
                time.sleep(1)
            
            # Once it lands, we move to 80% (Processing/Uploading phase)
            download.save_as(local_file)
            browser.close()
            
            file_size = os.path.getsize(local_file)
            supabase.table("jobs").update({
                "current_step": f"Uploading ({file_size // 1024} KB)", 
                "progress_percent": 85
            }).eq("id", job_id).execute()

            # Step 3: Supabase Storage
            file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
            with open(local_file, "rb") as f:
                supabase.storage.from_("videos").upload(file_name, f, {"x-upsert": "true"})

            # Step 4: Finalize
            supabase.table("jobs").update({
                "video_url": f"videos/{file_name}",
                "status": "waiting",
                "current_step": "Ready",
                "progress_percent": 100
            }).eq("id", job_id).execute()

    except Exception as e:
        print(f"❌ Error: {e}")
        supabase.table("jobs").update({"status": "failed", "error_message": str(e)[:200]}).eq("id", job_id).execute()
    finally:
        if local_file and os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url')
    if not video_url: return jsonify({"error": "No URL"}), 400

    job_res = supabase.table("jobs").insert({
        "video_url": "pending", 
        "status": "downloading",
        "progress_percent": 5,
        "current_step": "Initializing"
    }).execute()
    
    job_id = job_res.data[0]['id']
    threading.Thread(target=background_worker, args=(video_url, job_id)).start()
    return jsonify({"status": "success", "job_id": job_id}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
