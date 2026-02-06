import os
import time
import threading
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

def update_job_progress(job_id, progress, message, status="downloading", final_url=None):
    """Updates the database. Now handles the URL update as well."""
    try:
        data = {
            "progress_percent": progress,
            "current_step": message,
            "status": status
        }
        if final_url:
            data["video_url"] = final_url
            
        supabase.table("jobs").update(data).eq("id", job_id).execute()
        print(f"📊 [Job {job_id[:8]}] {progress}% - {message}")
    except Exception as e:
        print(f"⚠️ Progress Update Failed: {e}")

def background_worker(youtube_url, job_id):
    local_file = None
    timestamp = int(time.time())
    
    try:
        update_job_progress(job_id, 15, "Launching Automation Engine...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, 
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            update_job_progress(job_id, 30, "Navigating to Downr...")
            page.goto("https://downr.org", wait_until="domcontentloaded", timeout=60000)
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=120000)
            
            update_job_progress(job_id, 50, "Streaming from Google...")
            
            page.evaluate(f"(sel) => {{ const el = document.querySelector(sel); if(el) el.setAttribute('download', 'video.mp4'); }}", download_selector)

            with page.expect_download(timeout=300000) as download_info:
                page.click(download_selector)
            
            download = download_info.value
            local_file = f"/tmp/{timestamp}_video.mp4"
            download.save_as(local_file)
            browser.close()
            
            file_size = os.path.getsize(local_file)
            update_job_progress(job_id, 80, f"Uploading {file_size // 1024}KB to Supabase...")

            file_name = os.path.basename(local_file)
            with open(local_file, "rb") as f:
                supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

            # FINAL SUCCESS UPDATE: Switch status to 'waiting' and set real URL
            update_job_progress(
                job_id, 
                100, 
                "Download Complete", 
                status="waiting", 
                final_url=f"videos/{file_name}"
            )
            print(f"✅ [SUCCESS] Job {job_id} is ready for processing.")

    except Exception as e:
        error_msg = str(e)[:200]
        print(f"❌ [THREAD ERROR] {error_msg}")
        update_job_progress(job_id, 0, f"Error: {error_msg}", status="failed")
    finally:
        if local_file and os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.get_json()
    video_url = data.get('url')
    
    if not video_url:
        return jsonify({"error": "No URL"}), 400

    try:
        # --- THE FIX: Insert with a placeholder to satisfy NOT NULL ---
        job_res = supabase.table("jobs").insert({
            "video_url": "pending_download", # Satisfies database constraint
            "status": "downloading",
            "progress_percent": 5,
            "current_step": "Job Initialized",
            "tier_key": 1,
            "mode": "do",
            "priority": "low",
            "source": "website"
        }).execute()
        
        job_id = job_res.data[0]['id']
        print(f"🆕 Job Created in DB: {job_id}")

        thread = threading.Thread(target=background_worker, args=(video_url, job_id))
        thread.start()

        return jsonify({
            "status": "success",
            "job_id": job_id,
            "message": "Processing in background."
        }), 200

    except Exception as e:
        print(f"❌ API Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
