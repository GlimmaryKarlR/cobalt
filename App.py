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
    
    # --- ULTRA ROBUST OPTIONS ---
    ydl_opts = {
        # 1. Format: Best quality MP4 (merging video+audio)
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': local_file,
        
        # 2. Advanced Bypass: Mimic real traffic patterns
        'noprogress': True,
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 30,
        'retries': 15,
        'fragment_retries': 15,
        'retry_sleep_functions': {'http': lambda n: 5 * n}, # Exponential backoff
        
        # 3. Geo & Bot Bypass
        'geo_bypass': True,
        'add_header': [
            'Accept-Language: en-US,en;q=0.9',
            'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
        ],
        
        # 4. Atomic Integrity: Ensure file headers are correct
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
        'postprocessor_args': [
            '-movflags', 'faststart', # Moves moov atom to the front for AI tools
            '-threads', '4'           # Use more CPU for faster processing
        ],
    }

    try:
        print(f"🧵 [Job {job_id[:8]}] Initiating Ultra-Robust Download...")
        supabase.table("jobs").update({
            "current_step": "Downloading (yt-dlp Engine)", 
            "progress_percent": 35
        }).eq("id", job_id).execute()

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # We wrap the download in a try block to catch specific YouTube errors
            ydl.download([youtube_url])

        # Verification: Check if file exists and has data
        if not os.path.exists(local_file):
            raise Exception("File not found on disk after download.")
            
        size_mb = os.path.getsize(local_file) / (1024 * 1024)
        print(f"📦 Downloaded: {size_mb:.2f} MB")

        # 5. Upload to Supabase Storage
        supabase.table("jobs").update({
            "current_step": "Finalizing AI Cloud Storage", 
            "progress_percent": 85
        }).eq("id", job_id).execute()

        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f, {
                "content-type": "video/mp4",
                "x-upsert": "true"
            })

        # 6. Set status to 'waiting' for Geometry Engine
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()
        
        print(f"✅ [Job {job_id[:8]}] Pipeline complete.")

    except Exception as e:
        error_str = str(e)
        print(f"❌ Failure: {error_str}")
        supabase.table("jobs").update({
            "status": "failed", 
            "error_message": f"Critical Error: {error_str[:150]}"
        }).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    try:
        data = request.get_json()
        video_url = data.get('url') or (data.get('record') and data.get('record').get('url'))
        
        if not video_url:
            return jsonify({"status": "error", "message": "No URL provided"}), 400

        job_res = supabase.table("jobs").insert({
            "video_url": "pending", "status": "downloading", "progress_percent": 5,
            "current_step": "Initializing", "mode": "do", "tier_key": 1, "priority": "low"
        }).execute()
        
        job_id = job_res.data[0]['id']
        threading.Thread(target=background_worker, args=(video_url, job_id)).start()

        return jsonify({"status": "success", "id": job_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
