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
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def automate_downr_capture(youtube_url):
    """
    Automates the Downr.org interface to bypass YouTube blocks.
    Captures the resulting file and saves it to a temporary local path.
    """
    timestamp = int(time.time())
    save_path = f"/tmp/{timestamp}_video.mp4"
    
    with sync_playwright() as p:
        # Browser launch (Headless for Koyeb)
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Navigating to Downr for: {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

        # 1. Fill the URL input
        page.wait_for_selector("input[placeholder='Paste URL here']")
        page.fill("input[placeholder='Paste URL here']", youtube_url)

        # 2. Click the Download button
        # Downr usually disables the button until the URL is validated; we wait for it to be enabled if necessary.
        page.click("button:has-text('Download')")

        print("⏳ Waiting for Downr to process and generate 360p link...")

        # 3. Wait for the 360p link to appear
        # Increased timeout to 90s because server-side fetching can be slow
        page.wait_for_selector("a:has-text('360p')", timeout=90000)

        # 4. Trigger the download interception
        with page.expect_download() as download_info:
            page.click("a:has-text('360p')")
        
        download = download_info.value
        download.save_as(save_path)
        
        browser.close()
        print(f"✅ Local capture successful: {save_path}")
        return save_path

@app.route('/', methods=['GET'])
def health():
    return "Automation Engine Status: Online", 200

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.json
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "No URL provided"}), 400

    local_file = None
    try:
        # Step 1: Automate the download via Downr
        local_file = automate_downr_capture(video_url)
        
        if not os.path.exists(local_file):
            return jsonify({"error": "Automation finished but file missing"}), 500

        # Step 2: Upload to Supabase Storage
        file_name = os.path.basename(local_file)
        print(f"📤 Uploading {file_name} to Supabase...")
        
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(
                file_name, 
                f, 
                {"content-type": "video/mp4"}
            )

        # Step 3: Insert Job Record into Database
        job_entry = {
            "video_url": f"videos/{file_name}",
            "tier_key": 1,
            "mode": "do",
            "status": "pending",
            "priority": "low",
            "source": "website"
        }
        db_res = supabase.table("jobs").insert(job_entry).execute()

        # Step 4: Cleanup
        if os.path.exists(local_file):
            os.remove(local_file)

        return jsonify({
            "status": "success", 
            "job_id": db_res.data[0]['id'],
            "file_name": file_name
        })

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        # Cleanup on failure
        if local_file and os.path.exists(local_file):
            os.remove(local_file)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Ensure port 8080 for Koyeb
    app.run(host="0.0.0.0", port=8080)
