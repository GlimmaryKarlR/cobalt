import os
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

# --- Configuration ---
SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
# Make sure this is set in your Koyeb Environment Variables!
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def automate_downr_capture(youtube_url):
    """
    Automates Downr.org to fetch the video. 
    The browser is provided by the mcr.microsoft.com/playwright image.
    """
    timestamp = int(time.time())
    save_path = f"/tmp/{timestamp}_video.mp4"
    
    with sync_playwright() as p:
        # We do NOT specify executable_path. 
        # Playwright will find its twin browser in /ms-playwright/ automatically.
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Automating Downr for: {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

        # 1. Fill the URL
        page.wait_for_selector("input[placeholder='Paste URL here']")
        page.fill("input[placeholder='Paste URL here']", youtube_url)

        # 2. Click Download
        page.click("button:has-text('Download')")
        print("⏳ Processing... waiting for 360p link.")

        # 3. Wait for the link (Downr can take a moment to fetch from YouTube)
        page.wait_for_selector("a:has-text('360p')", timeout=90000)

        # 4. Intercept and save the download
        with page.expect_download() as download_info:
            page.click("a:has-text('360p')")
        
        download = download_info.value
        download.save_as(save_path)
        
        browser.close()
        return save_path

@app.route('/', methods=['GET'])
def health():
    return "Automation Engine: Online", 200

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.json
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "No URL"}), 400

    local_file = None
    try:
        # Step 1: Capture
        local_file = automate_downr_capture(video_url)
        
        # Step 2: Upload to Supabase
        file_name = os.path.basename(local_file)
        print(f"📤 Uploading {file_name} to Supabase...")
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(
                file_name, f, {"content-type": "video/mp4"}
            )

        # Step 3: Log Job
        job_data = {
            "video_url": f"videos/{file_name}",
            "status": "pending",
            "tier_key": 1,
            "mode": "do"
        }
        supabase.table("jobs").insert(job_data).execute()

        # Step 4: Cleanup
        if os.path.exists(local_file):
            os.remove(local_file)

        return jsonify({"status": "success", "file": file_name})

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        if local_file and os.path.exists(local_file):
            os.remove(local_file)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Koyeb requires host 0.0.0.0
    app.run(host="0.0.0.0", port=8080)
