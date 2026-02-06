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
    save_path = f"/tmp/{timestamp}_video.mp4"
    
    with sync_playwright() as p:
        # We use a standard launch here
        browser = p.chromium.launch(headless=True)
        
        # Initial context to get the link from Downr
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Step 1: Getting Link from Downr...")
        page.goto("https://downr.org", wait_until="networkidle", timeout=60000)
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Step 2: Extracting Video Link...")
        # Use a flexible selector for the download button
        selectors = ["a:has-text('360p')", "a:has-text('mp4')", "a[href*='googlevideo']"]
        page.wait_for_selector("a[href*='googlevideo']", timeout=90000)
        
        video_link = page.get_attribute("a[href*='googlevideo']", "href")
        if not video_link:
            browser.close()
            raise Exception("Could not find video link.")

        # --- THE FIX: The Dedicated Download Tab ---
        print(f"💾 Step 3: Downloading via Direct Stream...")
        
        # Create a second, clean page to isolate the video request from downr's CORS
        download_page = context.new_page()
        
        try:
            # We "expect" a response that contains the video data
            with download_page.expect_response(lambda res: res.url.startswith("https://") and "videoplayback" in res.url, timeout=120000) as response_info:
                # Navigating to the URL directly in a new tab bypasses Fetch/CORS errors
                download_page.goto(video_link)
            
            response = response_info.value
            print(f"🎯 Stream Intercepted. Status: {response.status}")
            
            buffer = response.body()
            
            if buffer and len(buffer) > 5000:
                with open(save_path, "wb") as f:
                    f.write(buffer)
                print(f"✅ Success: Saved {len(buffer)} bytes.")
            else:
                raise Exception(f"Buffer too small or empty ({len(buffer) if buffer else 0} bytes).")

            browser.close()
            return save_path

        except Exception as e:
            if 'browser' in locals(): browser.close()
            print(f"❌ Download Failed: {str(e)}")
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
        
        print(f"📤 Uploading to Supabase...")
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

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
