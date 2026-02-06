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

COOKIE_FILE = "youtube_cookies.txt"

def background_worker(youtube_url, job_id):
    local_file = f"/tmp/{job_id}.mp4"
    
    try:
        if not os.path.exists(COOKIE_FILE):
            print(f"❌ ERROR: {COOKIE_FILE} missing", flush=True)
            raise Exception(f"{COOKIE_FILE} not found")

        print(f"🧵 [Job {job_id[:8]}] Starting Download...", flush=True)
        
        # Exact 8-space indentation for the ydl_opts dictionary
        ydl_opts = {
            # Try to get a single file that already has video+audio
            'format': 'bestvideo+bestaudio/best', 
            'outtmpl': local_file,
            'cookiefile': COOKIE_FILE,
            'nocheckcertificate': True,
            'quiet': False,
            # This helps solve the "n challenge"
            'allow_unplayable_formats': True,
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        if os.path.exists(local_file):
            print(f"✅ Uploading {local_file}...", flush=True)
            file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
            with open(local_file, "rb") as f:
                supabase.storage.from_("videos").upload(file_name, f, {"content-type": "video/mp4"})

            supabase.table("jobs").update({
                "video_url": f"videos/{file_name}",
                "status": "waiting",
                "current_step": "Ready",
                "progress_percent": 100
            }).eq("id", job_id).execute()
        else:
            raise Exception("File creation failed")

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
    try:
        data = request.get_json()
        url = data.get('url') or (data.get('record') and data.get('record').get('url'))
        
        if not url:
            return jsonify({"error": "No URL provided"}), 400

        job_res = supabase.table("jobs").insert({
            "video_url": "pending", "status": "downloading", "progress_percent": 5,
            "current_step": "Initializing", "mode": "do", "tier_key": 1, "priority": "low"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(url, job_id)).start()
        return jsonify({"status": "success", "id": job_id}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
