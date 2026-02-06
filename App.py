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
SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def automate_downr_capture(youtube_url):
    timestamp = int(time.time())
    save_path = f"/tmp/{timestamp}_video.mp4"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Use a consistent User-Agent
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        context = browser.new_context(user_agent=ua)
        page = context.new_page()

        print(f"🚀 Step 1: Getting Link from Downr...")
        page.goto("https://downr.org", wait_until="networkidle")
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Step 2: Extracting Video Link...")
        page.wait_for_selector("a[href*='googlevideo']", timeout=90000)
        video_link = page.get_attribute("a[href*='googlevideo']", "href")

        # CRITICAL: Capture the cookies that Google/Downr set
        cookies = context.cookies()
        browser.close()

    # --- THE FIX: Session Hijacking ---
    print(f"💾 Step 3: Downloading via Authenticated Requests Session...")
    
    session = requests.Session()
    # Pass the Playwright cookies into the Requests session
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
    
    headers = {
        "User-Agent": ua,
        "Referer": "https://downr.org/",
        "Accept": "*/*"
    }

    try:
        # stream=True handles the 302 redirects automatically and won't freeze
        with session.get(video_link, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(save_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        
        file_size = os.path.getsize(save_path)
        if file_size < 10000:
            raise Exception(f"File too small ({file_size} bytes). Download likely failed.")
            
        print(f"✅ Success: Downloaded {file_size} bytes.")
        return save_path

    except Exception as e:
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
        
        print(f"📤 Uploading {file_name} to Supabase...")
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
