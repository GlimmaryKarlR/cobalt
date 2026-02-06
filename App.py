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

def background_worker(youtube_url):
    """
    Handles the long-running Playwright task without blocking the HTTP response.
    """
    timestamp = int(time.time())
    local_file = None
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            print(f"🎬 Background Start: {youtube_url}")
            page.goto("https://downr.org", wait_until="networkidle")
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            # Increased wait time for the button generation
            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=120000)

            # Force download attributes
            page.evaluate(f"(sel) => {{ const el = document.querySelector(sel); if(el) {{ el.setAttribute('download', 'video.mp4'); }} }}", download_selector)

            # Extended download timeout to 5 minutes (300,000ms)
            print("⏳ Starting 5-minute download window...")
            with page.expect_download(timeout=300000) as download_info:
                page.click(download_selector)
            
            download = download_info.value
            local_file = f"/tmp/{timestamp}_video.mp4"
            download.save_as(local_file)
            browser.close()

            # --- Post-Download Tasks ---
            file_name = os.path.basename(local_file)
            print(f"📤 Uploading {file_name}...")
            with open(local_file, "rb") as f:
                supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

            # Record job in DB
            supabase.table("jobs").insert({
                "video_url": f"videos/{file_name}",
                "tier_key": 1,
                "mode": "do",
                "status": "waiting"
            }).execute()
            print(f"✅ Background Task Complete: {file_name}")

    except Exception as e:
        print(f"❌ Background Error: {str(e)}")
    finally:
        if local_file and os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url')
    
    if not video_url:
        return jsonify({"error": "No URL"}), 400

    # Start the thread and return immediately
    thread = threading.Thread(target=background_worker, args=(video_url,))
    thread.start()

    return jsonify({
        "status": "accepted",
        "message": "Download started in background. Check your Supabase 'jobs' table in a few minutes."
    }), 202

if __name__ == "__main__":
    # Increased port timeout for safety
    app.run(host="0.0.0.0", port=8080)
