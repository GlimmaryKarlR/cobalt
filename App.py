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
    Automates Downr.org with a priority-based fallback for different qualities.
    """
    timestamp = int(time.time())
    save_path = f"/tmp/{timestamp}_video.mp4"
    
    with sync_playwright() as p:
        # Launch using the browsers baked into the Playwright Docker image
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Navigating to Downr for: {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

        # 1. Input URL and start conversion
        page.wait_for_selector("input[placeholder='Paste URL here']")
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Waiting for links to generate...")

        # 2. Define Fallback Selectors (Ordered by preference)
        # We wait for ANY of these to appear using a comma-separated CSS selector
        selectors = [
            "a:has-text('360p')",           # Format A (Standard)
            "a:has-text('mp4 (360p) avc1')",# Format B (Alternative Green)
            "a:has-text('mp4 (240p) avc1')",# Fallback Quality
            "a:has-text('mp4 (144p) avc1')" # Last Resort
        ]
        combined_selector = ", ".join(selectors)

        try:
            # Wait up to 90 seconds for any link to show up
            page.wait_for_selector(combined_selector, timeout=90000)
            
            # Find which specific one is actually visible
            target_selector = None
            for s in selectors:
                if page.locator(s).is_visible():
                    target_selector = s
                    print(f"🎯 Target identified: {s}")
                    break

            if not target_selector:
                raise Exception("Links appeared in DOM but are not visible.")

            # 3. Trigger Download (Using timeout=0 to wait indefinitely for the server to process)
            print("💾 Clicking download and waiting for stream to start...")
            with page.expect_download(timeout=0) as download_info:
                page.click(target_selector)
            
            download = download_info.value
            download.save_as(save_path)
            
            browser.close()
            print(f"✅ Download complete: {save_path}")
            return save_path

        except Exception as e:
            browser.close()
            print(f"❌ Automation Step Failed: {str(e)}")
            raise e

@app.route('/', methods=['GET'])
def health():
    return "Downloader Engine: Online", 200

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.json
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "Missing URL"}), 400

    local_file = None
    try:
        # Step 1: Run Playwright Automation
        local_file = automate_downr_capture(video_url)
        
        if not os.path.exists(local_file):
            return jsonify({"error": "File capture failed"}), 500

        # Step 2: Upload to Supabase Storage
        file_name = os.path.basename(local_file)
        print(f"📤 Uploading {file_name} to Supabase...")
        
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(
                file_name, 
                f, 
                {"content-type": "video/mp4"}
            )

        # Step 3: Insert Database Record
        job_payload = {
            "video_url": f"videos/{file_name}",
            "tier_key": 1,
            "mode": "do",
            "status": "pending",
            "priority": "low",
            "source": "website"
        }
        db_res = supabase.table("jobs").insert(job_payload).execute()

        # Step 4: Cleanup Local Temp File
        if os.path.exists(local_file):
            os.remove(local_file)

        return jsonify({
            "status": "success",
            "job_id": db_res.data[0]['id'],
            "file": file_name
        })

    except Exception as e:
        print(f"❌ Route Error: {str(e)}")
        if local_file and os.path.exists(local_file):
            os.remove(local_file)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Standard Koyeb Port
    app.run(host="0.0.0.0", port=8080)
