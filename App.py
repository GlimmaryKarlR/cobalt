import os
import time
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

# --- Configuration ---
SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def background_worker(youtube_url, job_id):
    local_file = None
    try:
        with sync_playwright() as p:
            # Launch with specific stability flags
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            # Step 1: Navigating to Downr
            supabase.table("jobs").update({"current_step": "Extracting Link", "progress_percent": 20}).eq("id", job_id).execute()
            page.goto("https://downr.org", wait_until="networkidle", timeout=60000)
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            # Step 2: Finding the dynamic link
            # We look for common download button patterns on Downr
            download_selector = "a[href*='googlevideo'], a:has-text('Download'), .download-button"
            page.wait_for_selector(download_selector, timeout=90000)
            
            # Step 3: Triggering Download
            supabase.table("jobs").update({"current_step": "Downloading Stream", "progress_percent": 50}).eq("id", job_id).execute()
            
            with page.expect_download(timeout=300000) as download_info:
                # Force a click even if overlapped
                page.click(download_selector, force=True)
            
            download = download_info.value
            local_file = f"/tmp/vid_{job_id[:8]}.mp4"
            download.save_as(local_file)
            browser.close()
            
            # Verify file exists and has size
            if not os.path.exists(local_file) or os.path.getsize(local_file) < 1000:
                raise Exception("Downloaded file is empty or missing.")

            # Step 4: Upload to Supabase
            supabase.table("jobs").update({"current_step": "Uploading to Storage", "progress_percent": 80}).eq("id", job_id).execute()
            file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
            
            with open(local_file, "rb") as f:
                storage_res = supabase.storage.from_("videos").upload(
                    file_name, f, {"content-type": "video/mp4", "x-upsert": "true"}
                )

            # --- SUCCESS SWITCH ---
            # Set video_url first, then status to 'waiting' for Hugging Face
            supabase.table("jobs").update({
                "video_url": f"videos/{file_name}",
                "status": "waiting",
                "current_step": "Ready for Processing",
                "progress_percent": 100
            }).eq("id", job_id).execute()
            
            print(f"✅ Job {job_id} is now LIVE for Hugging Face.")

    except Exception as e:
        error_msg = str(e)[:250]
        print(f"❌ Worker Failed: {error_msg}")
        supabase.table("jobs").update({
            "status": "failed", 
            "current_step": "Failed",
            "error_message": error_msg
        }).eq("id", job_id).execute()
    finally:
        if local_file and os.path.exists(local_file):
            try: os.remove(local_file)
            except: pass

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url')
    if not video_url: return jsonify({"error": "No URL"}), 400

    try:
        # Initial Row Creation
        job_res = supabase.table("jobs").insert({
            "video_url": "pending", 
            "status": "downloading",
            "progress_percent": 5,
            "current_step": "Initializing",
            "tier_key": 1,
            "mode": "do"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(video_url, job_id)).start()

        return jsonify({"status": "success", "job_id": job_id}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
