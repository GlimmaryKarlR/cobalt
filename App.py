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
    Simulates a native browser download to bypass IP-lock and 403 Forbidden errors.
    """
    timestamp = int(time.time())
    # We let Playwright choose the temp path first, then move it
    
    with sync_playwright() as p:
        # We MUST use a real browser download behavior
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True, # Crucial: tells the browser to allow file downloads
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Step 1: Loading Downr...")
        page.goto("https://downr.org", wait_until="networkidle")
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Step 2: Waiting for Download Button...")
        # We wait for the actual <a> tag that contains the googlevideo link
        download_selector = "a[href*='googlevideo']"
        page.wait_for_selector(download_selector, timeout=90000)

        # --- THE FIX: Trigger Native Download ---
        print("💾 Step 3: Triggering Native Browser Save...")
        try:
            with page.expect_download(timeout=120000) as download_info:
                # We click the link. If it opens a new tab, Playwright catches the stream.
                page.click(download_selector)
            
            download = download_info.value
            save_path = f"/tmp/{timestamp}_video.mp4"
            download.save_as(save_path)
            
            browser.close()
            
            file_size = os.path.getsize(save_path)
            print(f"✅ Success: Native Save complete ({file_size} bytes)")
            return save_path

        except Exception as e:
            if 'browser' in locals(): browser.close()
            print(f"❌ Native Save Failed: {str(e)}")
            raise e

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url')
    if not video_url: return jsonify({"error": "No URL"}), 400

    local_file = None
    try:
        local_file = automate_downr_capture(video_url)
        file_name = os.path.basename(local_file)
        
        print(f"📤 Uploading {file_name} to Supabase...")
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

        # Record job as 'waiting' for your worker
        supabase.table("jobs").insert({
            "video_url": f"videos/{file_name}",
            "tier_key": 1,
            "mode": "do",
            "status": "waiting",
            "priority": "low"
        }).execute()

        if os.path.exists(local_file): os.remove(local_file)
        return jsonify({"status": "success", "file": file_name})

    except Exception as e:
        print(f"❌ Workflow Error: {str(e)}")
        if local_file and os.path.exists(local_file): os.remove(local_file)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
