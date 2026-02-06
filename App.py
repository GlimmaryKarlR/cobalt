import os
import time
import threading
import base64
import yt_dlp
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def background_worker(youtube_url, job_id):
    local_file = f"/tmp/{job_id}.mp4"
    cookie_temp_file = f"/tmp/cookies_{job_id}.txt"
    
    try:
        # 1. Decode the Base64 Cookies from Environment Variable
        encoded_cookies = os.getenv("YOUTUBE_COOKIES")
        if not encoded_cookies:
            raise Exception("YOUTUBE_COOKIES variable is empty!")
            
        # Decode and write to temp file
        decoded_bytes = base64.b64decode(encoded_cookies)
        with open(cookie_temp_file, "wb") as f:
            f.write(decoded_bytes)

        supabase.table("jobs").update({"current_step": "Authenticated Download", "progress_percent": 30}).eq("id", job_id).execute()

        # 2. Configure yt-dlp
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': local_file,
            'cookiefile': cookie_temp_file,
            'socket_timeout': 30,
            'retries': 5,
            'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
            'postprocessor_args': ['-movflags', 'faststart'],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        # 3. Upload & Finalize
        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}", "status": "waiting",
            "current_step": "Ready", "progress_percent": 100
        }).eq("id", job_id).execute()

    except Exception as e:
        supabase.table("jobs").update({"status": "failed", "error_message": f"Auth/Build Error: {str(e)[:100]}"}).eq("id", job_id).execute()
    finally:
        for f in [local_file, cookie_temp_file]:
            if os.path.exists(f): os.remove(f)

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
