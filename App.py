import os
import time
import base64
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
    Downloads the video by streaming chunks from the browser context to Python.
    Bypasses 403 Forbidden errors by using the browser's authenticated session.
    """
    timestamp = int(time.time())
    save_path = f"/tmp/{timestamp}_video.mp4"
    
    with sync_playwright() as p:
        # Launch with security disabled to allow internal JS to fetch cross-origin video data
        browser = p.chromium.launch(headless=True, args=['--disable-web-security'])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Navigating to Downr for: {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

        # 1. Trigger Link Generation
        page.wait_for_selector("input[placeholder='Paste URL here']")
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Waiting for links to appear...")
        selectors = ["a:has-text('360p')", "a:has-text('mp4 (360p) avc1')", "a:has-text('mp4 (240p) avc1')"]
        page.wait_for_selector(", ".join(selectors), timeout=90000)
        
        # 2. Extract the Link
        video_link = None
        for s in selectors:
            loc = page.locator(s).first
            if loc.is_visible():
                video_link = loc.get_attribute("href")
                print(f"🎯 Target link found: {video_link[:60]}...")
                break

        if not video_link:
            browser.close()
            raise Exception("No valid download link found on page.")

        # 3. Stream Data via Browser JS
        print("💾 Extracting binary data from browser session...")
        try:
            # We pull the video data into the browser memory then pass it to Python as Base64
            b64_data = page.evaluate("""
                async (url) => {
                    const response = await fetch(url);
                    const arrayBuffer = await response.arrayBuffer();
                    const uint8Array = new Uint8Array(arrayBuffer);
                    let binary = '';
                    for (let i = 0; i < uint8Array.length; i++) {
                        binary += String.fromCharCode(uint8Array[i]);
                    }
                    return btoa(binary);
                }
            """, video_link)

            with open(save_path, "wb") as f:
                f.write(base64.b64decode(b64_data))
            
            browser.close()
            print(f"✅ Capture successful: {save_path}")
            return save_path

        except Exception as e:
            browser.close()
            print(f"❌ Data Extraction Failed: {str(e)}")
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
        # Step 1: Download from Downr
        local_file = automate_downr_capture(video_url)
        
        # Step 2: Upload to Supabase Storage
        file_name = os.path.basename(local_file)
        print(f"📤 Uploading {file_name} to Supabase storage...")
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(
                file_name, 
                f, 
                {"content-type": "video/mp4"}
            )

        # Step 3: Insert Database Job with 'waiting' status
        # This matches your worker polling loop
        job_payload = {
            "video_url": f"videos/{file_name}",
            "tier_key": 1,
            "mode": "do",
            "status": "waiting",   # <--- THE FIX: Correct status for check constraint
            "priority": "low",
            "source": "website"
        }
        
        print(f"📝 Creating database record with status 'waiting'...")
        db_res = supabase.table("jobs").insert(job_payload).execute()

        # Step 4: Cleanup
        if os.path.exists(local_file):
            os.remove(local_file)

        return jsonify({
            "status": "success", 
            "file": file_name,
            "job_id": db_res.data[0]['id'] if db_res.data else "created"
        })

    except Exception as e:
        print(f"❌ Route Failure: {str(e)}")
        if local_file and os.path.exists(local_file):
            os.remove(local_file)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Standard port for Koyeb deployment
    app.run(host="0.0.0.0", port=8080)
