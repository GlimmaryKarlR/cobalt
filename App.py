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
    local_file = f"/tmp/vid_{job_id[:8]}.mp4"
    try:
        with sync_playwright() as p:
            print(f"🧵 [Job {job_id[:8]}] Launching Browser...")
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            # Set a realistic window size and user agent
            context = browser.new_context(
                accept_downloads=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            supabase.table("jobs").update({"current_step": "Extracting Link", "progress_percent": 15}).eq("id", job_id).execute()
            
            page.goto("https://downr.org", wait_until="networkidle")
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            # Look for the download button
            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=60000)
            
            # INSTEAD OF REQUESTS: Use Playwright's native download handler
            # This keeps the session, cookies, and headers identical to the browser
            print(f"📡 [Job {job_id[:8]}] Triggering Browser Download...")
            supabase.table("jobs").update({"current_step": "Downloading (Browser)", "progress_percent": 40}).eq("id", job_id).execute()

            with page.expect_download(timeout=300000) as download_info:
                # Some sites need a 'force' click if the link is under an overlay
                page.click(download_selector, force=True)
            
            download = download_info.value
            # This waits for the download to finish completely
            download.save_as(local_file)
            
            browser.close()

        # Step 3: Upload
        print(f"📤 [Job {job_id[:8]}] Uploading to Storage...")
        supabase.table("jobs").update({"current_step": "Uploading", "progress_percent": 85}).eq("id", job_id).execute()
        
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
        print(f"✅ [Job {job_id[:8]}] Success!")

    except Exception as e:
        print(f"❌ [Job {job_id[:8]}] Error: {e}")
        supabase.table("jobs").update({"status": "failed", "error_message": str(e)[:250]}).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    try:
        data = request.get_json()
        video_url = data.get('url') or (data.get('record') and data.get('record').get('url'))
        
        job_res = supabase.table("jobs").insert({
            "video_url": "pending_download", 
            "status": "downloading",
            "progress_percent": 5,
            "current_step": "Initializing",
            "mode": "do", "tier_key": 1, "priority": "low", "source": "website"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(video_url, job_id)).start()
        return jsonify(job_res.data[0]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
