import os
import time
import threading
import yt_dlp
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def progress_hook(d, job_id):
    """Callback for yt-dlp to update Supabase in real-time."""
    if d['status'] == 'downloading':
        p = d.get('_percent_str', '0%').replace('%','')
        try:
            percent = float(p)
            # Map 0-100% of download to 10-90% of total job progress
            scaled_progress = int(10 + (percent * 0.8))
            
            # Update every 10% to avoid hitting Supabase rate limits
            if scaled_progress % 10 == 0:
                supabase.table("jobs").update({
                    "progress_percent": scaled_progress,
                    "current_step": f"Downloading: {p}%"
                }).eq("id", job_id).execute()
        except:
            pass

def background_worker(youtube_url, job_id):
    local_file = f"/tmp/{job_id}.mp4"
    
    ydl_opts = {
        'format': 'best[ext=mp4]',
        'outtmpl': local_file,
        'progress_hooks': [lambda d: progress_hook(d, job_id)],
        'quiet': True,
        'no_warnings': True,
    }

    try:
        # Step 1: Download using yt-dlp (much more stable than scraping)
        print(f"📡 [Job {job_id[:8]}] Starting yt-dlp download...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])

        # Step 2: Upload to Supabase
        print(f"📤 [Job {job_id[:8]}] Uploading...")
        supabase.table("jobs").update({"current_step": "Uploading", "progress_percent": 95}).eq("id", job_id).execute()
        
        file_name = f"{int(time.time())}_{job_id[:8]}.mp4"
        with open(local_file, "rb") as f:
            supabase.storage.from_("videos").upload(file_name, f)

        # Step 3: Finalize for Hugging Face
        supabase.table("jobs").update({
            "video_url": f"videos/{file_name}",
            "status": "waiting",
            "current_step": "Ready",
            "progress_percent": 100
        }).eq("id", job_id).execute()
        print(f"✅ [Job {job_id[:8]}] Complete!")

    except Exception as e:
        print(f"❌ [Job {job_id[:8]}] Failed: {e}")
        supabase.table("jobs").update({"status": "failed", "error_message": str(e)[:200]}).eq("id", job_id).execute()
    finally:
        if os.path.exists(local_file):
            os.remove(local_file)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    try:
        data = request.get_json()
        video_url = data.get('url') or (data.get('record') and data.get('record').get('url'))
        
        # 1. Create the row (Immediate Response)
        job_res = supabase.table("jobs").insert({
            "video_url": "pending_download", 
            "status": "downloading",
            "progress_percent": 5,
            "current_step": "Starting...",
            "mode": "do", "tier_key": 1, "priority": "low", "source": "website"
        }).execute()
        
        job_id = job_res.data[0]['id']
        
        # 2. Spawn thread and RETURN IMMEDIATELY
        # This prevents the Edge Function from timing out!
        thread = threading.Thread(target=background_worker, args=(video_url, job_id))
        thread.start()

        return jsonify({"status": "success", "job_id": job_id}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
