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
    Automates Downr.org with a priority-based fallback.
    Uses .first to bypass Strict Mode Violations when multiple links appear.
    """
    timestamp = int(time.time())
    save_path = f"/tmp/{timestamp}_video.mp4"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print(f"🚀 Navigating to Downr for: {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

        # 1. Fill the URL and click Download
        page.wait_for_selector("input[placeholder='Paste URL here']")
        page.fill("input[placeholder='Paste URL here']", youtube_url)
        page.click("button:has-text('Download')")

        print("⏳ Waiting for links to generate...")

        # 2. Priority list of link labels
        selectors = [
            "a:has-text('360p')",           # Primary button
            "a:has-text('mp4 (360p) avc1')",# Alternative green
            "a:has-text('mp4 (240p) avc1')",# Fallback 1
            "a:has-text('mp4 (144p) avc1')" # Fallback 2
        ]
        combined_selector = ", ".join(selectors)

        try:
            # Wait up to 90s for any of the above links to appear
            page.wait_for_selector(combined_selector, timeout=90000)
            
            # 3. Find the best visible link and use .first to avoid strict mode errors
            target_locator = None
            for s in selectors:
                loc = page.locator(s).first  # <--- CRITICAL FIX: .first added
                if loc.is_visible():
                    target_locator = loc
                    print(f"🎯 Target identified: {s}")
                    break

            if not target_locator:
                raise Exception("Links were found in DOM but none were visible.")

            # 4. Handle the download
            print("💾 Triggering download...")
            with page.expect_download(timeout=0) as download_info:
                target_locator.click()
            
            download = download_info.value
            download.save_as(save_path)
            
            browser.close()
            print(f"✅ Local capture successful: {save_path}")
            return save_path

        except Exception as e:
            browser.close()
            print(f"❌ Automation failed: {str(e)}")
            raise e

@app.route('/', methods=['GET'])
def health():
    return "Automation Engine Status: Online", 200

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.json
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "No URL provided"}), 400

    local_file = None
    try:
        # Step 1: Automate capture
        local_file = automate_downr_capture(video_url)
        
        if not os.path.exists(local_file):
            return jsonify({"error": "File was not saved locally"}), 500

        # Step 2: Upload to Supabase Storage
        file_name = os.path.basename(local_file)
        print(f"📤 Uploading {file_name} to Supabase...")
        
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(
                file_name, 
                f, 
                {"content-type": "video/mp4"}
            )

        # Step 3: Insert Database Entry
        job_entry = {
            "video_url": f"videos/{file_name}",
            "tier_key": 1,
            "mode": "do",
            "status": "pending",
            "priority": "low",
            "source": "website"
        }
        db_res = supabase.table("jobs").insert(job_entry).execute()

        # Step 4: Final Cleanup
        if os.path.exists(local_file):
            os.remove(local_file)

        return jsonify({
            "status": "success", 
            "job_id": db_res.data[0]['id'] if db_res.data else "n/a",
            "file_name": file_name
        })

    except Exception as e:
        print(f"❌ Route Error: {str(e)}")
        if local_file and os.path.exists(local_file):
            os.remove(local_file)
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Ensure port 8080 for Koyeb
    app.run(host="0.0.0.0", port=8080)
