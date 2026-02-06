import os
import time
import threading
import yt_dlp
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

# Configuration
SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# The file you are overwriting in your repo
COOKIE_FILE = "youtube_cookies.txt"

def background_worker(youtube_url, job_id):
    local_file = f"/tmp/{job_id}.mp4"
    
    try:
        # 1. VERIFY FILE (Crucial for debugging)
        if not os.path.exists(COOKIE_FILE):
            print(f"❌ CRITICAL ERROR: {COOKIE_FILE} not found! Directory contents: {os.listdir('.')}", flush=True)
            raise Exception(f"{COOKIE_FILE} missing from root")

        print(f"🧵 [Job {job_id[:8]}] Starting Authenticated Download...", flush=True)
        
        supabase.table("jobs").update({
            "current_step": "Downloading with Session Cookies", 
            "progress_percent": 30
        }).eq("id", job_id).execute()

        ydl_opts = {
            'format': 'best',
            'outtmpl': local_file,
            'cookiefile': COOKIE_FILE,  # <--- FIXED: Now matches your variable
            'nocheckcertificate': True,
            'impersonate': 'chrome', 
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.5',
                'Origin': 'https://www.youtube.com',
                'Referer': 'https://www.youtube.com/',
            },
            'external_downloader': 'ffmpeg',
            'external_downloader_args': {
                'ffmpeg_i': [
                    '-reconnect', '1', 
                    '-reconnect_streamed', '1', 
                    '-reconnect_delay_max', '5',
                    '-headers', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36' + '\r\n'
                ]
            },
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            'postprocessor_args': ['-movflags', 'faststart'],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        if not os.path.exists(local_file):
            # Check if maybe it downloaded as .mkv or something else despite our request
            raise Exception("FFmpeg failed to produce the final .mp4 file.")

        print(f"✅ Downloaded locally. Uploading to Supabase...", flush=True)

        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()
        
        print(f"🚀 [Job {job_id[:8]}] Success!", flush=True)

    except Exception as e:
        error_text = str(e)
        print(f"❌ Failure: {error_text}", flush=True)
        supabase.table("jobs").update({
            "status": "failed", 
            "error_message": error_text[:200]
        }).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file): 
            os.remove(local_file)
            
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
    return jsonify({"status": "success", "id": job_id}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
