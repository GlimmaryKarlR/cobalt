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
    Downloads the video by executing a fetch inside the browser context.
    Disables web security to bypass CORS restrictions during the fetch.
    """
    timestamp = int(time.time())
    save_path = f"/tmp/{timestamp}_video.mp4"
    
    with sync_playwright() as p:
        # CRITICAL FIX: Add args=['--disable-web-security'] to bypass the "Failed to fetch" CORS error
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process'
            ]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Navigating to Downr for: {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

        # 1. Generate the links
        page.wait_for_selector("input[placeholder='Paste URL here']")
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Waiting for links...")
        selectors = ["a:has-text('360p')", "a:has-text('mp4 (360p) avc1')", "a:has-text('mp4 (240p) avc1')"]
        page.wait_for_selector(", ".join(selectors), timeout=90000)
        
        # 2. Extract the href
        video_link = None
        for s in selectors:
            loc = page.locator(s).first
            if loc.is_visible():
                video_link = loc.get_attribute("href")
                print(f"🎯 Target link extracted: {video_link[:50]}...")
                break

        if not video_link:
            browser.close()
            raise Exception("Direct link extraction failed.")

        # 3. NATIVE BROWSER FETCH (CORS Bypass active)
        print("💾 Downloading via Browser Context (Security Disabled)...")
        
        try:
            # We wrap the fetch in a try/catch inside JS to get better error reporting
            b64_data = page.evaluate("""
                async (url) => {
                    try {
                        const response = await fetch(url);
                        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                        const blob = await response.blob();
                        return new Promise((resolve, reject) => {
                            const reader = new FileReader();
                            reader.onloadend = () => resolve(reader.result.split(',')[1]);
                            reader.onerror = reject;
                            reader.readAsDataURL(blob);
                        });
                    } catch (e) {
                        return { error: e.message };
                    }
                }
            """, video_link)

            # Handle errors returned from inside the evaluate block
            if isinstance(b64_data, dict) and 'error' in b64_data:
                raise Exception(f"JS Fetch Error: {b64_data['error']}")

            # 4. Save Base64 to File
            with open(save_path, "wb") as f:
                f.write(base64.b64decode(b64_data))
            
            browser.close()
            print(f"✅ Success: {save_path}")
            return save_path

        except Exception as e:
            browser.close()
            print(f"❌ Automation Step Failed: {str(e)}")
            raise e

@app.route('/', methods=['GET'])
def health():
    return "Engine: Online", 200

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "No URL provided"}), 400

    local_file = None
    try:
        local_file = automate_downr_capture(video_url)
        
        # Upload to Supabase
        file_name = os.path.basename(local_file)
        print(f"📤 Uploading {file_name}...")
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

        # Log Job
        job_data = {
            "video_url": f"videos/{file_name}",
            "status": "pending",
            "tier_key": 1,
            "mode": "do",
            "priority": "low",
            "source": "website"
        }
        db_res = supabase.table("jobs").insert(job_data).execute()

        if os.path.exists(local_file):
            os.remove(local_file)

        return jsonify({"status": "success", "file": file_name})

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        if local_file and os.path.exists(local_file):
            os.remove(local_file)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
