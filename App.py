import os
import time
import binascii
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
    Extracts video by fetching data as a Hex string inside the browser.
    Hex prevents the truncation/corruption issues seen with Base64/atob.
    """
    timestamp = int(time.time())
    save_path = f"/tmp/{timestamp}_video.mp4"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--disable-web-security'])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Navigating to Downr: {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

        page.wait_for_selector("input[placeholder='Paste URL here']")
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Generating links...")
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
            raise Exception("Video link not found.")

        print("💾 Extracting binary via Hex stream (to prevent 'moov atom' errors)...")
        try:
            # Using Hex instead of Base64 to avoid browser-side string encoding limits
            hex_data = page.evaluate("""
                async (url) => {
                    const response = await fetch(url);
                    const buffer = await response.arrayBuffer();
                    const uint8 = new Uint8Array(buffer);
                    return Array.from(uint8)
                        .map(b => b.toString(16).padStart(2, '0'))
                        .join('');
                }
            """, video_link)

            # Convert Hex string back to raw binary bytes
            with open(save_path, "wb") as f:
                f.write(binascii.unhexlify(hex_data))
            
            browser.close()
            # Verify file size (should be > 0)
            if os.path.getsize(save_path) < 1000:
                raise Exception("Captured file is too small, likely corrupted.")
                
            print(f"✅ Capture complete: {save_path} ({os.path.getsize(save_path)} bytes)")
            return save_path

        except Exception as e:
            browser.close()
            print(f"❌ Extraction Failed: {str(e)}")
            raise e

@app.route('/', methods=['GET'])
def health():
    return "Engine: Online", 200

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "No URL"}), 400

    local_file = None
    try:
        local_file = automate_downr_capture(video_url)
        file_name = os.path.basename(local_file)
        
        print(f"📤 Uploading {file_name}...")
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(
                file_name, f, {"content-type": "video/mp4"}
            )

        job_payload = {
            "video_url": f"videos/{file_name}",
            "tier_key": 1,
            "mode": "do",
            "status": "waiting",
            "priority": "low",
            "source": "website"
        }
        
        print(f"📝 Job created in DB.")
        db_res = supabase.table("jobs").insert(job_payload).execute()

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
