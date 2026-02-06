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
    try:
        with sync_playwright() as p:
            print(f"🧵 [Job {job_id[:8]}] Launching Manual Override Browser...")
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            # 1. Navigation
            supabase.table("jobs").update({"current_step": "Loading Downloader", "progress_percent": 15}).eq("id", job_id).execute()
            page.goto("https://downr.org", wait_until="networkidle")

            # 2. Injection (Instead of Pasting)
            # We target the input field directly. 
            input_selector = "input[placeholder='Paste URL here']"
            page.wait_for_selector(input_selector)
            page.click(input_selector)
            page.fill(input_selector, youtube_url)
            print(f"📥 [Job {job_id[:8]}] URL Injected.")

            # 3. Trigger the initial 'Download' click to start server-side processing
            # We wait for the blue button to be clickable
            convert_button = "button:has-text('Download')"
            page.wait_for_selector(convert_button)
            page.click(convert_button)
            
            # 4. The "Wait for Enable" Logic
            # The button you saw was 'disabled=""'. We wait for that to disappear
            # or for the link <a> tag to replace it.
            print(f"⏳ [Job {job_id[:8]}] Waiting for site to generate MP4 stream...")
            supabase.table("jobs").update({"current_step": "Bypassing Throttler (Wait 30-90s)", "progress_percent": 40}).eq("id", job_id).execute()

            # This selector looks for the final clickable link that points to Google's video servers
            final_link_selector = "a[href*='googlevideo']"
            
            # High quality videos take longer. We give it 120 seconds.
            page.wait_for_selector(final_link_selector, state="visible", timeout=120000)

            # 5. Native Download
            print(f"🎯 [Job {job_id[:8]}] Link ready. Starting transfer.")
            supabase.table("jobs").update({"current_step": "Streaming File", "progress_percent": 60}).eq("id", job_id).execute()

            with page.expect_download(timeout=600000) as download_info:
                page.click(final_link_selector)
            
            download = download_info.value
            download.save_as(local_file)
            browser.close()

        # 6. Integrity & Storage Upload
        file_size = os.path.getsize(local_file)
        if file_size < 1000000:
            raise Exception("Download interrupted: File too small.")

        supabase.table("jobs").update({"current_step": "Finalizing Storage", "progress_percent": 85}).eq("id", job_id).execute()
        
        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

        # 7. Success - Hand off to Hugging Face
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()
        print(f"✅ [Job {job_id[:8]}] Done.")

    except Exception as e:
        error_text = str(e)[:150]
        print(f"❌ [Job {job_id[:8]}] Error: {error_text}")
        supabase.table("jobs").update({"status": "failed", "error_message": f"Pipeline Error: {error_text}"}).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file): os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    try:
        data = request.get_json()
        url = data.get('url') or (data.get('record') and data.get('record').get('url'))
        if not url: return jsonify({"status": "error", "message": "No URL"}), 400

        job_res = supabase.table("jobs").insert({
            "video_url": "pending", "status": "downloading", "progress_percent": 5, "current_step": "Initializing"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(url, job_id)).start()
        return jsonify({"status": "success", "job_id": job_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
