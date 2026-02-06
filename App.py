import os
import time
import threading
import yt_dlp
from flask import Flask, request, jsonify
from flask_cors import CORS
from playwright.sync_api import sync_playwright
from supabase import create_client, Client
from http.cookiejar import MozillaCookieJar, Cookie

app = Flask(__name__)
CORS(app)

SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def background_worker(youtube_url, job_id):
    local_file = f"/tmp/{job_id}.mp4"
    cookie_file = f"/tmp/cookies_{job_id}.txt"
    
    try:
        print(f"🕵️‍♂️ [Job {job_id[:8]}] Getting fresh cookies via Playwright...")
        supabase.table("jobs").update({"current_step": "Authenticating session", "progress_percent": 10}).eq("id", job_id).execute()
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
            page = context.new_page()
            
            # Go directly to YouTube to get the most relevant cookies
            page.goto("https://www.youtube.com", wait_until="networkidle")
            time.sleep(3) 
            
            playwright_cookies = context.cookies()
            
            # Use MozillaCookieJar to handle the formatting properly
            jar = MozillaCookieJar(cookie_file)
            for c in playwright_cookies:
                # This fixes the AssertionError by correctly identifying domain dots
                domain = c['domain']
                initial_dot = domain.startswith('.')
                
                ck = Cookie(
                    version=0, name=c['name'], value=c['value'],
                    port=None, port_specified=False,
                    domain=domain, domain_specified=True, domain_initial_dot=initial_dot,
                    path=c['path'], path_specified=True,
                    secure=c['secure'],
                    expires=c.get('expires', 2147483647),
                    discard=False, comment=None, comment_url=None, rest={'HttpOnly': None}, rfc2109=False
                )
                jar.set_cookie(ck)
            jar.save(ignore_discard=True, ignore_expires=True)
            browser.close()

        print(f"📡 [Job {job_id[:8]}] Starting download with corrected cookies...")
        
        ydl_opts = {
            'format': 'best[ext=mp4]',
            'outtmpl': local_file,
            'cookiefile': cookie_file,
            'nocheckcertificate': True,
            'quiet': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        # Step 3: Upload
        supabase.table("jobs").update({"current_step": "Uploading", "progress_percent": 90}).eq("id", job_id).execute()
        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f)

        # Step 4: Finalize
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()
        print(f"✅ [Job {job_id[:8]}] Success!")

    except Exception as e:
        print(f"❌ [Job {job_id[:8]}] Error: {str(e)}")
        supabase.table("jobs").update({"status": "failed", "error_message": str(e)[:250]}).eq("id", job_id).execute()
    finally:
        for f in [local_file, cookie_file]:
            if os.path.exists(f): os.remove(f)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    # ... (Keep existing process_link entry point) ...
    data = request.get_json()
    video_url = data.get('url') or (data.get('record') and data.get('record').get('url'))
    job_res = supabase.table("jobs").insert({
        "video_url": "pending", "status": "downloading", "progress_percent": 5,
        "current_step": "Initializing", "mode": "do", "tier_key": 1, "priority": "low", "source": "website"
    }).execute()
    job_id = job_res.data[0]['id']
    threading.Thread(target=background_worker, args=(video_url, job_id)).start()
    return jsonify(job_res.data[0]), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
