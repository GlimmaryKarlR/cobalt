import os
import time
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def background_worker(youtube_url, job_id):
    local_file = f"/tmp/{job_id}.mp4"
    try:
        with sync_playwright() as p:
            print(f"🧵 [Job {job_id[:8]}] Launching Browser (Native Mode)...")
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            supabase.table("jobs").update({
                "current_step": "Finding Video Stream", 
                "progress_percent": 20
            }).eq("id", job_id).execute()

            # 1. Navigate and Search
            page.goto("https://downr.org", wait_until="networkidle")
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            # 2. Wait for the link to appear
            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=60000)
            
            print(f"📡 [Job {job_id[:8]}] Link found. Forcing Native Download...")
            supabase.table("jobs").update({
                "current_step": "Downloading (Native Browser Stream)", 
                "progress_percent": 45
            }).eq("id", job_id).execute()

            # 3. CAPTURE THE DOWNLOAD
            # We use a 'with' block to catch the event the moment the click happens
            with page.expect_download(timeout=300000) as download_info:
                # We use dispatch_event to bypass any 'overlay' blocks on the site
                page.eval_on_selector(download_selector, "el => el.click()")
            
            download = download_info.value
            print(f"📥 [Job {job_id[:8]}] Stream caught: {download.suggested_filename}")
            
            # This line is where it usually 'stalls'—it's actually just downloading!
            download.save_as(local_file)
            browser.close()

        # 4. UPLOAD
        if os.path.exists(local_file):
            file_size = os.path.getsize(local_file)
            print(f"📤 [Job {job_id[:8]}] Uploading {file_size // 1024} KB to Supabase...")
            
            supabase.table("jobs").update({
                "current_step": "Uploading to Storage", 
                "progress_percent": 85
            }).eq("id", job_id).execute()

            file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
            with open(local_file, "rb") as f:
                supabase.storage.from_("videos").upload(file_name, f)

            # 5. FINALIZE
            supabase.table("jobs").update({
                "video_url": f"videos/{file_name}",
                "status": "waiting",
                "current_step": "Ready",
                "progress_percent": 100
            }).eq("id", job_id).execute()
            print(f"✅ [Job {job_id[:8]}] Complete.")
        else:
            raise Exception("File was not saved correctly by browser.")

    except Exception as e:
        print(f"❌ [Job {job_id[:8]}] Failed: {str(e)}")
        supabase.table("jobs").update({
            "status": "failed", 
            "error_message": str(e)[:250]
        }).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url') or (data.get('record') and data.get('record').get('url'))
    
    # Create the row and return immediately to the Edge Function
    job_res = supabase.table("jobs").insert({
        "video_url": "pending", "status": "downloading", "progress_percent": 5,
        "current_step": "Initializing", "mode": "do", "tier_key": 1,
        "priority": "low", "source": "website"
    }).execute()
    
    job_id = job_res.data[0]['id']
    threading.Thread(target=background_worker, args=(video_url, job_id)).start()
    
    return jsonify(job_res.data[0]), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
