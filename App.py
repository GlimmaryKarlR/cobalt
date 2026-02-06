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
    local_file = f"/tmp/{job_id}.mp4"
    debug_screenshot = f"/tmp/debug_{job_id}.png"
    
    try:
        with sync_playwright() as p:
            print(f"🧵 [Job {job_id[:8]}] Launching Hunter Browser...")
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            context = browser.new_context(
                accept_downloads=True,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # 1. Navigation & Injection
            supabase.table("jobs").update({"current_step": "Navigating to Downloader", "progress_percent": 15}).eq("id", job_id).execute()
            page.goto("https://downr.org", wait_until="networkidle", timeout=60000)

            input_selector = "input[placeholder='Paste URL here']"
            page.wait_for_selector(input_selector)
            page.fill(input_selector, youtube_url)
            
            # Click the blue 'Download' button to start conversion
            page.click("button:has-text('Download')")

            # 2. The "Wait for Link" Loop
            # We wait for the <a> tag to appear which replaces the disabled <button>
            print(f"📡 [Job {job_id[:8]}] Waiting for server to finish conversion...")
            supabase.table("jobs").update({"current_step": "Server Processing (Wait 30-90s)", "progress_percent": 30}).eq("id", job_id).execute()

            # Target the specific googlevideo link or the final download button
            final_link_selector = "a[href*='googlevideo'], a:has-text('Download')"
            
            # Use a long timeout (120s) for high-quality video processing
            page.wait_for_selector(final_link_selector, state="visible", timeout=120000)
            
            # 3. Download Execution
            print(f"🎯 [Job {job_id[:8]}] Link active! Downloading...")
            supabase.table("jobs").update({"current_step": "Downloading to Worker", "progress_percent": 60}).eq("id", job_id).execute()

            with page.expect_download(timeout=600000) as download_info:
                page.click(final_link_selector)
            
            download = download_info.value
            download.save_as(local_file)
            browser.close()

        # 4. Integrity Check & Storage Upload
        if os.path.getsize(local_file) < 1000000:
            raise Exception("File too small or download failed.")

        supabase.table("jobs").update({"current_step": "Finalizing Storage", "progress_percent": 85}).eq("id", job_id).execute()
        
        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

        # 5. Success
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()

    except Exception as e:
        error_msg = f"Worker Error: {str(e)[:150]}"
        print(f"❌ {error_msg}")
        # Capture screenshot on failure for Supabase debugging
        try:
            page.screenshot(path=debug_screenshot)
            with open(debug_screenshot, "rb") as f:
                supabase.storage.from_("videos").upload(f"debug/error_{job_id}.png", f)
        except: pass
        
        supabase.table("jobs").update({"status": "failed", "error_message": error_msg}).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file): os.remove(local_file)
        if os.path.exists(debug_screenshot): os.remove(debug_screenshot)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    try:
        data = request.get_json()
        url = data.get('url') or (data.get('record') and data.get('record').get('url'))
        if not url: return jsonify({"status": "error", "message": "No URL"}), 400

        # FIX: Added 'mode', 'tier_key', and 'priority' to satisfy Supabase NOT NULL constraints
        job_res = supabase.table("jobs").insert({
            "video_url": "pending", 
            "status": "downloading", 
            "progress_percent": 5,
            "current_step": "Initializing",
            "mode": "do",
            "tier_key": 1,
            "source": "website",
            "priority": "low"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(url, job_id)).start()
        return jsonify({"status": "success", "job_id": job_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
