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
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Step 1: Generating Link for {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

        page.wait_for_selector("input[placeholder='Paste URL here']")
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Step 2: Extracting Video Address...")
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
            raise Exception("Failed to extract video link.")

        # --- REPAIRED CAPTURE LOGIC ---
        print(f"💾 Step 3: Draining stream from Google Servers...")
        
        # We use the page's internal request wait to ensure the buffer is filled
        try:
            with page.expect_response(lambda res: video_link in res.url, timeout=120000) as response_info:
                # Instead of goto, we trigger a fetch which is more stable for background data
                page.evaluate(f"fetch('{video_link}')")
            
            response = response_info.value
            buffer = response.body() # This blocks until the full body is received

            if buffer and len(buffer) > 1000:
                with open(save_path, "wb") as f:
                    f.write(buffer)
                print(f"✅ Success: Saved {len(buffer)} bytes.")
            else:
                raise Exception("Buffer capture returned empty or insufficient data.")

            browser.close()
            return save_path

        except Exception as e:
            if 'browser' in locals(): browser.close()
            print(f"❌ Capture Failed: {str(e)}")
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

        job_payload = {
            "video_url": f"videos/{file_name}",
            "tier_key": 1,
            "mode": "do",
            "status": "waiting",
            "priority": "low"
        }
        supabase.table("jobs").insert(job_payload).execute()

        if os.path.exists(local_file): os.remove(local_file)
        return jsonify({"status": "success", "file": file_name})

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        if local_file and os.path.exists(local_file): os.remove(local_file)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
