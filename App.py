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

def background_worker(youtube_url, job_id):
    local_file = f"/tmp/{job_id}.mp4"
    cookie_temp_file = f"/tmp/cookies_{job_id}.txt"
    
    try:
        # 1. Inject Cookies from Environment Variable
        cookie_data = os.getenv("YOUTUBE_COOKIES")
        if not cookie_data:
            raise Exception("YOUTUBE_COOKIES environment variable is missing!")
            
        with open(cookie_temp_file, "w") as f:
            f.write(cookie_data)

        print(f"🧵 [Job {job_id[:8]}] Starting Authenticated Download...")
        supabase.table("jobs").update({
            "current_step": "Downloading with Session Cookies", 
            "progress_percent": 30
        }).eq("id", job_id).execute()

        # 2. Configure yt-dlp with the temporary cookie file
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': local_file,
            'cookiefile': cookie_temp_file,  # CRITICAL: Pointing to the new file
            'socket_timeout': 30,
            'retries': 10,
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            'postprocessor_args': ['-movflags', 'faststart'],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        if not os.path.exists(local_file):
            raise Exception("Download failed: File not found on disk.")

        # 3. Upload to Supabase
        file_size = os.path.getsize(local_file)
        supabase.table("jobs").update({
            "current_step": "Finalizing Cloud Transfer", 
            "progress_percent": 85
        }).eq("id", job_id).execute()

        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

        # 4. Success Handoff
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()
        
        print(f"✅ [Job {job_id[:8]}] Success!")

    except Exception as e:
        print(f"❌ Failure: {str(e)}")
        supabase.table("jobs").update({
            "status": "failed", 
            "error_message": f"Auth Error: {str(e)[:100]}"
        }).eq("id", job_id).execute()
    finally:
        # Cleanup sensitive data
        if os.path.exists(local_file): os.remove(local_file)
        if os.path.exists(cookie_temp_file): os.remove(cookie_temp_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    try:
        data = request.get_json()
        url = data.get('url') or (data.get('record') and data.get('record').get('url'))
        
        job_res = supabase.table("jobs").insert({
            "video_url": "pending", "status": "downloading", "progress_percent": 5,
            "current_step": "Initializing", "mode": "do", "tier_key": 1, "priority": "low"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(url, job_id)).start()
        return jsonify({"status": "success", "id": job_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
