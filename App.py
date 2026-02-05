import os
import time
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

# --- Configuration ---
# Ensure these match your environment variables in Koyeb
SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def automate_downr_capture(youtube_url):
    timestamp = int(time.time())
    save_path = f"/tmp/{timestamp}_video.mp4"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # 1. Define a consistent User-Agent
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        context = browser.new_context(user_agent=ua)
        page = context.new_page()

        print(f"🚀 Navigating to Downr for: {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

        page.wait_for_selector("input[placeholder='Paste URL here']")
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Waiting for links...")
        selectors = ["a:has-text('360p')", "a:has-text('mp4 (360p) avc1')", "a:has-text('mp4 (240p) avc1')"]
        page.wait_for_selector(", ".join(selectors), timeout=90000)
        
        video_link = None
        for s in selectors:
            loc = page.locator(s).first
            if loc.is_visible():
                video_link = loc.get_attribute("href")
                break

        if not video_link:
            browser.close()
            raise Exception("Direct link extraction failed.")

        # 2. STEAL THE COOKIES from the browser session
        playwright_cookies = context.cookies()
        # Convert to format Requests library understands
        session_cookies = {c['name']: c['value'] for c in playwright_cookies}

        # 3. DOWNLOAD with full browser identity
        print("💾 Downloading via authenticated stream...")
        try:
            with requests.Session() as s:
                # Give Requests the same "face" as the browser
                s.headers.update({"User-Agent": ua})
                s.cookies.update(session_cookies)
                
                with s.get(video_link, stream=True, timeout=300) as r:
                    r.raise_for_status()
                    with open(save_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=32768):
                            f.write(chunk)
            
            browser.close()
            return save_path
        except Exception as e:
            browser.close()
            raise e

@app.route('/', methods=['GET'])
def health():
    return "Automation Engine: Operational", 200

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "No URL provided"}), 400

    local_file = None
    try:
        # Step 1: Capture the file
        local_file = automate_downr_capture(video_url)
        
        if not os.path.exists(local_file):
            return jsonify({"error": "File capture failed"}), 500

        # Step 2: Upload to Supabase Storage
        file_name = os.path.basename(local_file)
        print(f"📤 Uploading {file_name} to Supabase storage...")
        
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(
                file_name, 
                f, 
                {"content-type": "video/mp4"}
            )

        # Step 3: Log Job in Database
        job_data = {
            "video_url": f"videos/{file_name}",
            "tier_key": 1,
            "mode": "do",
            "status": "pending",
            "priority": "low",
            "source": "website"
        }
        db_res = supabase.table("jobs").insert(job_data).execute()

        # Step 4: Cleanup
        if os.path.exists(local_file):
            os.remove(local_file)

        return jsonify({
            "status": "success",
            "job_id": db_res.data[0]['id'] if db_res.data else "n/a",
            "file": file_name
        })

    except Exception as e:
        print(f"❌ Route Failure: {str(e)}")
        if local_file and os.path.exists(local_file):
            os.remove(local_file)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Host must be 0.0.0.0 for Koyeb/Docker
    app.run(host="0.0.0.0", port=8080)
