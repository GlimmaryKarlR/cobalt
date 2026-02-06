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

def background_worker(youtube_url, job_id):
    local_file = f"/tmp/{job_id}.mp4"
    try:
        with sync_playwright() as p:
            print(f"🧵 [Job {job_id[:8]}] Launching Fast-Stream Browser...")
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            # 1. Start Conversion
            supabase.table("jobs").update({"current_step": "Extracting Video Link", "progress_percent": 20}).eq("id", job_id).execute()
            page.goto("https://downr.org", wait_until="networkidle")
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            # 2. Grab Direct Link (Bypassing the 'Click' wait)
            selector = "a[href*='googlevideo']"
            page.wait_for_selector(selector, state="visible", timeout=60000)
            
            # Instead of clicking and waiting, we grab the raw URL
            direct_link = page.get_attribute(selector, "href")
            browser.close()

        if not direct_link:
            raise Exception("Direct link not found")

        # 3. Use Requests to Stream (Much more reliable for status updates)
        print(f"📡 [Job {job_id[:8]}] Streaming 5s video...")
        supabase.table("jobs").update({"current_step": "Streaming Video", "progress_percent": 60}).eq("id", job_id).execute()
        
        response = requests.get(direct_link, stream=True, timeout=30)
        with open(local_file, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk: f.write(chunk)

        # 4. Upload to Supabase
        file_size = os.path.getsize(local_file)
        supabase.table("jobs").update({"current_step": "Uploading to AI", "progress_percent": 85}).eq("id", job_id).execute()
        
        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

        # 5. Finalize
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()
        print(f"✅ [Job {job_id[:8]}] Complete.")

    except Exception as e:
        supabase.table("jobs").update({"status": "failed", "error_message": str(e)}).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file): os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    url = data.get('url') or (data.get('record') and data.get('record').get('url'))
    job_res = supabase.table("jobs").insert({
        "video_url": "pending", "status": "downloading", "progress_percent": 5,
        "current_step": "Initializing", "mode": "do", "tier_key": 1, "priority": "low"
    }).execute()
    job_id = job_res.data[0]['id']
    threading.Thread(target=background_worker, args=(url, job_id)).start()
    return jsonify({"status": "success", "job_id": job_id}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
