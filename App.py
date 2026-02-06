import os
import time
import threading
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

def background_worker(youtube_url, job_id):
    local_file = f"/tmp/vid_{job_id[:8]}.mp4"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            # We capture cookies to pass them to requests for granular tracking
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            page = context.new_page()

            # Step 1: Extract the link
            supabase.table("jobs").update({"current_step": "Extracting Link", "progress_percent": 10}).eq("id", job_id).execute()
            page.goto("https://downr.org", wait_until="networkidle")
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=60000)
            
            video_url = page.get_attribute(download_selector, "href")
            cookies = {c['name']: c['value'] for c in context.cookies()}
            user_agent = context.evaluate("navigator.userAgent")
            browser.close()

        # Step 2: Granular Download with Requests
        print(f"📡 Starting Stream Download for {job_id}")
        headers = {"User-Agent": user_agent}
        
        with requests.get(video_url, cookies=cookies, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            last_reported_percent = 15

            with open(local_file, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            # Calculate percent between 15% and 80%
                            percent = int(15 + (downloaded / total_size) * 65)
                            # Only update DB every 10% to avoid rate limits
                            if percent >= last_reported_percent + 10:
                                supabase.table("jobs").update({
                                    "progress_percent": percent,
                                    "current_step": f"Downloading ({downloaded // 1024} KB)"
                                }).eq("id", job_id).execute()
                                last_reported_percent = percent

        # Step 3: Upload to Supabase
        supabase.table("jobs").update({"current_step": "Uploading", "progress_percent": 85}).eq("id", job_id).execute()
        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f)

        # Step 4: Finalize for Hugging Face
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()
        print(f"✅ Job {job_id} complete.")

    except Exception as e:
        print(f"❌ Error: {e}")
        supabase.table("jobs").update({"status": "failed", "error_message": str(e)}).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url')
    if not video_url: return jsonify({"error": "No URL"}), 400

    try:
        # --- THE FIX: Included 'mode' and 'tier_key' to satisfy NOT NULL ---
        job_res = supabase.table("jobs").insert({
            "video_url": "pending", 
            "status": "downloading",
            "progress_percent": 5,
            "current_step": "Initializing",
            "mode": "do",        # Added
            "tier_key": 1,       # Added
            "priority": "low",
            "source": "website"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(video_url, job_id)).start()
        return jsonify({"status": "success", "job_id": job_id}), 200

    except Exception as e:
        print(f"❌ API Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
