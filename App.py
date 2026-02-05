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
    """
    Automates Downr.org to generate a link, extracts the href, 
    and downloads the file directly via requests to avoid playback stalls.
    """
    timestamp = int(time.time())
    save_path = f"/tmp/{timestamp}_video.mp4"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # We still use a real User-Agent to keep the request looking organic
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Navigating to Downr for: {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

        # 1. Fill the URL and trigger conversion
        page.wait_for_selector("input[placeholder='Paste URL here']")
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Waiting for links to generate...")

        # 2. Priority selectors for different video qualities
        selectors = [
            "a:has-text('360p')",           
            "a:has-text('mp4 (360p) avc1')",
            "a:has-text('mp4 (240p) avc1')",
            "a:has-text('mp4 (144p) avc1')" 
        ]
        combined_selector = ", ".join(selectors)

        try:
            # Wait for Downr's backend to provide the links
            page.wait_for_selector(combined_selector, timeout=90000)
            
            # 3. Find the best available link and grab the URL (href)
            video_link = None
            for s in selectors:
                loc = page.locator(s).first
                if loc.is_visible():
                    video_link = loc.get_attribute("href")
                    print(f"🎯 Target link extracted: {video_link[:50]}...")
                    break

            if not video_link:
                raise Exception("Links found in DOM but href attribute is missing.")

            # 4. DOWNLOAD DIRECTLY (The Bypass)
            # We use stream=True for large files and a long timeout for slow servers
            print("💾 Downloading file via direct stream (bypassing browser playback)...")
            
            # We copy the cookies/headers from the browser session if needed, 
            # though usually Downr links are IP-bound and don't require them.
            with requests.get(video_link, stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        if chunk:
                            f.write(chunk)
            
            browser.close()
            print(f"✅ Download complete: {save_path}")
            return save_path

        except Exception as e:
            if 'browser' in locals():
                browser.close()
            print(f"❌ Automation Error: {str(e)}")
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
