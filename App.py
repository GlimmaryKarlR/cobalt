import os
import time
import threading
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
    """Handles the heavy lifting in a detached thread."""
    local_file = f"/tmp/{job_id}.mp4"
    try:
        with sync_playwright() as p:
            print(f"🧵 [Job {job_id[:8]}] Launching Browser...")
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            # Step 1: Navigate to the bypass site
            supabase.table("jobs").update({"current_step": "Finding Stream", "progress_percent": 20}).eq("id", job_id).execute()
            
            page.goto("https://downr.org", wait_until="networkidle", timeout=60000)
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            # Step 2: Catch the Google Video link
            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=60000)
            
            print(f"📡 [Job {job_id[:8]}] Stream found. Starting native download...")
            supabase.table("jobs").update({"current_step": "Downloading (Browser Stream)", "progress_percent": 45}).eq("id", job_id).execute()

            # Step 3: Native Browser Download
            with page.expect_download(timeout=600000) as download_info:
                page.eval_on_selector(download_selector, "el => el.click()")
            
            download = download_info.value
            download.save_as(local_file)
            browser.close()

        # Step 4: Upload to Supabase Storage
        if os.path.exists(local_file):
            print(f"📤 [Job {job_id[:8]}] Uploading to Storage...")
            supabase.table("jobs").update({"current_step": "Finalizing Upload", "progress_percent": 85}).eq("id", job_id).execute()

            file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
            with open(local_file, "rb") as f:
                supabase.storage.from_("videos").upload(file_name, f, {"x-upsert": "true"})

            # Step 5: Finalize row for Hugging Face (Status 'waiting' triggers the next AI step)
            supabase.table("jobs").update({
                "video_url": f"videos/{file_name}",
                "status": "waiting",
                "current_step": "Ready",
                "progress_percent": 100
            }).eq("id", job_id).execute()
            print(f"✅ [Job {job_id[:8]}] Worker Finished Successfully.")
        else:
            raise Exception("File was not saved to local disk.")

    except Exception as e:
        error_msg = str(e)[:250]
        print(f"❌ [Job {job_id[:8]}] Worker Error: {error_msg}")
        supabase.table("jobs").update({
            "status": "failed", 
            "error_message": f"Worker Error: {error_msg}"
        }).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    """API Entry Point."""
    try:
        data = request.get_json()
        # Accept both direct and record-wrapped payloads
        video_url = data.get('url') or (data.get('record') and data.get('record').get('url'))
        
        if not video_url:
            return jsonify({"status": "error", "message": "No URL provided"}), 400

        # Create row immediately
        job_res = supabase.table("jobs").insert({
            "video_url": "pending", 
            "status": "downloading",
            "progress_percent": 5,
            "current_step": "Initializing",
            "mode": "do", "tier_key": 1, "priority": "low", "source": "website"
        }).execute()
        
        job_data = job_res.data[0]
        job_id = job_data['id']
        
        # Detach background thread
        thread = threading.Thread(target=background_worker, args=(video_url, job_id))
        thread.start()

        # Return what the Edge Function expects
        return jsonify({
            "status": "success",
            "id": job_id,
            "job_id": job_id,
            "message": "Worker started successfully"
        }), 200

    except Exception as e:
        print(f"🔥 Flask API Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    # Koyeb default port
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
