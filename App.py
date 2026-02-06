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
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            # Step 1: Navigating
            supabase.table("jobs").update({"current_step": "Extracting Link", "progress_percent": 20}).eq("id", job_id).execute()
            page.goto("https://downr.org", wait_until="domcontentloaded")
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=60000)
            
            # Step 2: Downloading
            supabase.table("jobs").update({"current_step": "Downloading Stream", "progress_percent": 50}).eq("id", job_id).execute()
            with page.expect_download(timeout=300000) as download_info:
                page.click(download_selector)
            
            download = download_info.value
            local_file = f"/tmp/{int(time.time())}_video.mp4"
            download.save_as(local_file)
            browser.close()
            
            # Step 3: Uploading
            supabase.table("jobs").update({"current_step": "Uploading to Supabase", "progress_percent": 80}).eq("id", job_id).execute()
            file_name = os.path.basename(local_file)
            with open(local_file, "rb") as f:
                supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

            # --- THE SWITCH ---
            # Now that the file is safe, we change status to 'waiting' 
            # This is the signal for Hugging Face to start.
            supabase.table("jobs").update({
                "video_url": f"videos/{file_name}",
                "status": "waiting",
                "current_step": "Ready for Processing",
                "progress_percent": 100
            }).eq("id", job_id).execute()
            
            print(f"✅ Job {job_id} is now LIVE for Hugging Face.")

    except Exception as e:
        print(f"❌ Worker Failed: {e}")
        supabase.table("jobs").update({"status": "failed", "current_step": f"Error: {str(e)[:50]}"}).eq("id", job_id).execute()
    finally:
        if local_file and os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url')
    if not video_url: return jsonify({"error": "No URL"}), 400

    try:
        # Start with 'downloading' status - Hugging Face will ignore this
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
