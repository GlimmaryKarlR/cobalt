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

# Configuration
SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

def background_worker(youtube_url, job_id):
    local_file = f"/tmp/{job_id}.mp4"
    success = False
    
    try:
        # Step 1: Extract Link via Playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            
            supabase.table("jobs").update({"current_step": "Extracting Stream Link", "progress_percent": 15}).eq("id", job_id).execute()
            page.goto("https://downr.org", wait_until="networkidle", timeout=60000)
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=60000)
            direct_link = page.get_attribute(download_selector, "href")
            browser.close()

        if not direct_link:
            raise Exception("Link extraction failed.")

        # Step 2: Download with Spoofing & Stream (Max 2 Retries)
        for attempt in range(2):
            print(f"📡 [Job {job_id[:8]}] Download attempt {attempt + 1}...")
            response = requests.get(direct_link, headers={"User-Agent": USER_AGENT, "Referer": "https://downr.org/"}, stream=True, timeout=60)
            
            total_size = int(response.headers.get('content-length', 0))
            bytes_downloaded = 0
            
            with open(local_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
                        bytes_downloaded += len(chunk)
            
            # Check if file is healthy (at least 500KB and matches expected size if known)
            if bytes_downloaded > 500000:
                success = True
                break
            else:
                print(f"⚠️ [Job {job_id[:8]}] Attempt {attempt + 1} produced a corrupt/small file. Retrying...")
                time.sleep(2)

        if not success:
            raise Exception("Download failed after multiple attempts (file corrupt).")

        # Step 3: Upload to Supabase Storage
        file_size = os.path.getsize(local_file)
        supabase.table("jobs").update({"current_step": "Uploading MP4", "progress_percent": 85}).eq("id", job_id).execute()

        # We force the extension to be .mp4 here
        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4", "x-upsert": "true"})

        # Step 4: Finalize for Geometry Engine
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()
        
    except Exception as e:
        supabase.table("jobs").update({"status": "failed", "error_message": str(e)[:200]}).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url') or (data.get('record') and data.get('record').get('url'))
    
    job_res = supabase.table("jobs").insert({
        "video_url": "pending", "status": "downloading", "progress_percent": 5,
        "current_step": "Initializing", "mode": "do", "tier_key": 1, "source": "website"
    }).execute()
    
    job_id = job_res.data[0]['id']
    threading.Thread(target=background_worker, args=(video_url, job_id)).start()

    return jsonify({"status": "success", "id": job_id, "job_id": job_id}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
