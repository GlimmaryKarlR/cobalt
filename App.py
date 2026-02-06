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
    timestamp = int(time.time())
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Step 1: Loading Downr for {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle")
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Step 2: Waiting for Download Button...")
        download_selector = "a[href*='googlevideo']"
        page.wait_for_selector(download_selector, timeout=60000)

        # --- THE FIX: Force 'Download' Attribute ---
        # We inject JS to ensure the browser doesn't try to play the video.
        print("🔧 Injecting force-download attributes...")
        page.evaluate(f"""
            (sel) => {{
                const el = document.querySelector(sel);
                if (el) {{
                    el.setAttribute('download', 'video.mp4');
                    el.setAttribute('target', '_self');
                }}
            }}
        """, download_selector)

        print("💾 Step 3: Capturing Download...")
        try:
            with page.expect_download(timeout=90000) as download_info:
                # Clicking the modified link now triggers the download manager
                page.click(download_selector)
            
            download = download_info.value
            save_path = f"/tmp/{timestamp}_video.mp4"
            download.save_as(save_path)
            
            browser.close()
            return save_path

        except Exception as e:
            if 'browser' in locals(): browser.close()
            raise Exception(f"Download failed or timed out: {str(e)}")

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

        # Final Database Entry
        supabase.table("jobs").insert({
            "video_url": f"videos/{file_name}",
            "tier_key": 1,
            "mode": "do",
            "status": "waiting"
        }).execute()

        if os.path.exists(local_file): os.remove(local_file)
        return jsonify({"status": "success", "file": file_name})

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        if local_file and os.path.exists(local_file): os.remove(local_file)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
