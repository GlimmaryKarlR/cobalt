import os
import time
import threading
import random
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
    local_file = f"/tmp/{job_id}.mp4"
    debug_screenshot = f"/tmp/debug_{job_id}.png"
    
    try:
        with sync_playwright() as p:
            print(f"🧵 [Job {job_id[:8]}] Launching Debug Browser...")
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = browser.new_context(
                accept_downloads=True,
                viewport={'width': 1280, 'height': 720}
            )
            page = context.new_page()

            # 1. Navigate
            supabase.table("jobs").update({"current_step": "Navigating to Downloader", "progress_percent": 15}).eq("id", job_id).execute()
            page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

            # 2. Input URL
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            time.sleep(1)
            page.keyboard.press("Enter")

            # 3. Handle Potential Ad Popups & Wait for Link
            print(f"📡 [Job {job_id[:8]}] Waiting for download link to generate...")
            supabase.table("jobs").update({"current_step": "Waiting for Server Response", "progress_percent": 30}).eq("id", job_id).execute()

            try:
                # We wait for the specific download link
                # If it fails, we take a screenshot before crashing
                selector = "a[href*='googlevideo']"
                page.wait_for_selector(selector, timeout=45000)
                
                # Human-like click
                download_btn = page.locator(selector)
                download_btn.scroll_into_view_if_needed()
                
                with page.expect_download(timeout=600000) as download_info:
                    download_btn.click()
                
                download = download_info.value
                download.save_as(local_file)
                print(f"✅ [Job {job_id[:8]}] Downloaded to disk.")

            except Exception as e:
                # SAVE SCREENSHOT ON FAILURE
                page.screenshot(path=debug_screenshot)
                with open(debug_screenshot, "rb") as f:
                    supabase.storage.from_("videos").upload(f"debug/error_{job_id}.png", f)
                print(f"📸 Debug screenshot uploaded to storage/videos/debug/error_{job_id}.png")
                raise e

            browser.close()

        # 4. Integrity and Upload
        file_size = os.path.getsize(local_file)
        if file_size < 500000: raise Exception("File truncated.")

        supabase.table("jobs").update({"current_step": "Uploading to Supabase", "progress_percent": 85}).eq("id", job_id).execute()
        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4", "x-upsert": "true"})

        # 5. Finalize
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()

    except Exception as e:
        error_msg = f"Worker Error: {str(e)[:150]}"
        print(f"❌ {error_msg}")
        supabase.table("jobs").update({"status": "failed", "error_message": error_msg}).eq("id", job_id).execute()
    finally:
        for f in [local_file, debug_screenshot]:
            if os.path.exists(f): os.remove(f)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    try:
        data = request.get_json()
        url = data.get('url') or (data.get('record') and data.get('record').get('url'))
        if not url: return jsonify({"status": "error", "message": "No URL"}), 400

        job_res = supabase.table("jobs").insert({
            "video_url": "pending", "status": "downloading", "progress_percent": 5,
            "current_step": "Initializing", "mode": "do", "tier_key": 1, "source": "website"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(url, job_id)).start()
        return jsonify({"status": "success", "id": job_id, "job_id": job_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
