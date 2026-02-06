import os
import time
import threading
import yt_dlp
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
    cookie_file = f"/tmp/cookies_{job_id}.txt"
    
    try:
        # STEP 1: Use Playwright to generate fresh cookies
        print(f"🕵️‍♂️ [Job {job_id[:8]}] Stealing cookies from browser...")
        supabase.table("jobs").update({"current_step": "Bypassing Bot Detection", "progress_percent": 10}).eq("id", job_id).execute()
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
            page = context.new_page()
            
            # Visit the downloader site to get valid session cookies
            page.goto("https://downr.org", wait_until="networkidle")
            time.sleep(2) 
            
            # Save cookies to a Netscape formatted file for yt-dlp
            cookies = context.cookies()
            with open(cookie_file, 'w') as f:
                f.write("# Netscape HTTP Cookie File\n")
                for c in cookies:
                    domain = c['domain']
                    path = c['path']
                    expires = int(c.get('expires', time.time() + 3600))
                    secure = "TRUE" if c['secure'] else "FALSE"
                    name = c['name']
                    value = c['value']
                    f.write(f"{domain}\tTRUE\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
            browser.close()

        # STEP 2: Use yt-dlp with the stolen cookies
        print(f"📡 [Job {job_id[:8]}] Starting download with cookies...")
        
        ydl_opts = {
            'format': 'best[ext=mp4]',
            'outtmpl': local_file,
            'cookiefile': cookie_file, # <--- THE BYPASS
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        # STEP 3: Upload
        supabase.table("jobs").update({"current_step": "Uploading", "progress_percent": 90}).eq("id", job_id).execute()
        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f)

        # STEP 4: Finalize
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()
        print(f"✅ [Job {job_id[:8]}] Successfully bypassed and downloaded!")

    except Exception as e:
        print(f"❌ [Job {job_id[:8]}] Bot Detection still too strong: {e}")
        supabase.table("jobs").update({"status": "failed", "error_message": "Bot detection blocked the download"}).eq("id", job_id).execute()
    finally:
        for f in [local_file, cookie_file]:
            if os.path.exists(f): os.remove(f)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    # ... (Keep the exact same code from previous message for process_link) ...
    data = request.get_json()
    video_url = data.get('url') or (data.get('record') and data.get('record').get('url'))
    job_res = supabase.table("jobs").insert({
        "video_url": "pending", "status": "downloading", "progress_percent": 5,
        "current_step": "Initializing", "mode": "do", "tier_key": 1
    }).execute()
    job_id = job_res.data[0]['id']
    threading.Thread(target=background_worker, args=(video_url, job_id)).start()
    return jsonify({"status": "success", "job_id": job_id}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
