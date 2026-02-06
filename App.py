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
# Ensure these are set in your Koyeb Environment Variables
SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def background_worker(youtube_url, job_id):
    """
    Handles the heavy lifting: Browser automation -> Streaming download -> Supabase Upload.
    """
    local_file = f"/tmp/vid_{job_id[:8]}.mp4"
    
    try:
        # Step 1: Use Playwright to extract the actual Google Video link
        with sync_playwright() as p:
            print(f"🧵 [Job {job_id[:8]}] Launching Playwright...")
            browser = p.chromium.launch(
                headless=True, 
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # Update DB to show we are starting
            supabase.table("jobs").update({
                "current_step": "Extracting Link", 
                "progress_percent": 10
            }).eq("id", job_id).execute()
            
            # Navigate to Downr
            page.goto("https://downr.org", wait_until="networkidle", timeout=60000)
            page.fill("input[placeholder='Paste URL here']", youtube_url)
            page.click("button:has-text('Download')")

            # Wait for the dynamic download link to appear
            download_selector = "a[href*='googlevideo']"
            page.wait_for_selector(download_selector, timeout=60000)
            
            final_download_url = page.get_attribute(download_selector, "href")
            
            # Capture cookies to bypass Google's 403 Forbidden checks on the stream
            cookies = {c['name']: c['value'] for c in context.cookies()}
            browser.close()

        # Step 2: Stream the video using Requests for granular progress
        print(f"📡 [Job {job_id[:8]}] Starting Stream Download...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        }
        
        with requests.get(final_download_url, cookies=cookies, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            last_reported_percent = 20

            with open(local_file, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024): # 1MB chunks
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            # Map download progress to the 20% -> 80% range
                            percent = int(20 + (downloaded / total_size) * 60)
                            
                            # Only update Supabase every 10% to avoid spamming/rate-limits
                            if percent >= last_reported_percent + 10:
                                print(f"📊 [Job {job_id[:8]}] Download Progress: {percent}%")
                                supabase.table("jobs").update({
                                    "progress_percent": percent,
                                    "current_step": f"Downloading ({downloaded // 1024 // 1024}MB / {total_size // 1024 // 1024}MB)"
                                }).eq("id", job_id).execute()
                                last_reported_percent = percent

        # Step 3: Upload the finished file to Supabase Storage
        print(f"📤 [Job {job_id[:8]}] Uploading to Storage...")
        supabase.table("jobs").update({
            "current_step": "Uploading to Storage", 
            "progress_percent": 85
        }).eq("id", job_id).execute()
        
        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(
                path=file_name, 
                file=f, 
                file_options={"content-type": "video/mp4", "x-upsert": "true"}
            )

        # Step 4: Finalize and trigger the Hugging Face Worker
        # We set the status to 'waiting' and provide the real video_url here.
        print(f"✅ [Job {job_id[:8]}] Process Complete. Setting to 'waiting'.")
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready for Processing",
            "progress_percent": 100
        }).eq("id", job_id).execute()

    except Exception as e:
        error_msg = str(e)[:250]
        print(f"❌ [Job {job_id[:8]}] Worker Failed: {error_msg}")
        supabase.table("jobs").update({
            "status": "failed", 
            "current_step": "Failed",
            "error_message": error_msg
        }).eq("id", job_id).execute()
        
    finally:
        # Cleanup the temp file to keep the container light
        if os.path.exists(local_file):
            try:
                os.remove(local_file)
            except:
                pass

@app.route('/api/process-link', methods=['POST'])
def process_link():
    """
    Entry point for the Supabase Edge Function.
    Creates the row immediately and spawns the background thread.
    """
    try:
        data = request.get_json()
        # Support both direct calls and Supabase Webhook payload formats
        video_url = data.get('url') or (data.get('record') and data.get('record').get('url'))
        
        if not video_url:
            return jsonify({"status": "error", "message": "No URL found"}), 400

        # 1. Insert Initial Row
        # This satisfies all Not-Null constraints and the 'waiting' status check.
        # Hugging Face will ignore this because video_url is 'pending_download'.
        job_res = supabase.table("jobs").insert({
            "video_url": "pending_download", 
            "status": "downloading", # Ensure you've run the SQL to allow this status
            "progress_percent": 5,
            "current_step": "Initializing",
            "mode": "do",
            "tier_key": 1,
            "priority": "low",
            "source": "website"
        }).execute()
        
        job_data = job_res.data[0]
        job_id = job_data['id']
        
        print(f"🆕 [API] Created Job: {job_id}")

        # 2. Start Background Thread
        thread = threading.Thread(target=background_worker, args=(video_url, job_id))
        thread.start()

        # 3. Return the full job object so the Edge Function is happy
        return jsonify(job_data), 200

    except Exception as e:
        print(f"🔥 [API] Flask Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    # Koyeb requires the app to listen on 0.0.0.0
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
