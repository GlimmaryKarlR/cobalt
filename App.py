import os
import subprocess
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
from playwright.sync_api import sync_playwright

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
# In Koyeb, set SUPABASE_SERVICE_ROLE_KEY (found in Supabase Settings > API)
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") 
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def generate_netscape_cookies():
    """
    Replicates 'Downr' extension logic to create a valid Netscape cookies.txt.
    """
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://www.youtube.com")
            raw_cookies = context.cookies()
            
            lines = [
                "# Netscape HTTP Cookie File",
                "# http://curl.haxx.se/rfc/cookie_spec.html",
                "# This is a generated file! Do not edit.",
                ""
            ]
            
            for c in raw_cookies:
                domain = c['domain']
                flag = "TRUE" if domain.startswith('.') else "FALSE"
                path = c['path']
                secure = "TRUE" if c['secure'] else "FALSE"
                expiry = str(int(c.get('expires', 0)))
                line = f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{c['name']}\t{c['value']}"
                lines.append(line)
                
            with open("cookies.txt", "w") as f:
                f.write("\n".join(lines))
            browser.close()
    except Exception as e:
        print(f"Cookie generation failed: {e}")

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.json
    video_url = data.get('url')
    
    if not video_url:
        return jsonify({"error": "No URL provided"}), 400

    # Match your existing naming convention: timestamp_id.mp4
    timestamp = int(time.time() * 1000)
    video_id = video_url.split('=')[-1] if '=' in video_url else "ext"
    filename = f"{timestamp}_{video_id}.mp4"
    temp_raw = f"raw_{filename}"

    try:
        # 1. Prepare Cookies
        generate_netscape_cookies()
        
        # 2. Download and Fix (FastStart + 3:01 limit)
        download_cmd = [
            "yt-dlp",
            "--cookies", "cookies.txt",
            "--match-filter", "duration <= 181",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", temp_raw,
            "--exec", f"ffmpeg -i {temp_raw} -c copy -movflags +faststart {filename} && rm {temp_raw}",
            video_url
        ]
        
        process = subprocess.run(download_cmd, capture_output=True, text=True)
        
        if "does not pass filter duration <= 181" in process.stdout:
            return jsonify({"status": "error", "message": "Video exceeds 3:01 limit."}), 400

        if not os.path.exists(filename):
            return jsonify({"status": "error", "message": "Processing failed."}), 500

        # 3. Upload to Supabase 'videos' bucket
        storage_path = filename # root of the bucket
        with open(filename, "rb") as f:
            supabase.storage.from_("videos").upload(
                file=f,
                path=storage_path,
                file_options={"content-type": "video/mp4", "upsert": "true"}
            )

        # 4. Insert into the 'jobs' table using your headers
        job_entry = {
            "video_url": f"videos/{storage_path}", # Matching your table format
            "tier_key": 1,
            "mode": "do",
            "status": "pending",
            "priority": "low",
            "source": "website",
            "progress_percent": 0,
            "current_step": "Queued from external link",
            "user_id": data.get('user_id') # Received from App.tsx
        }
        
        db_response = supabase.table("jobs").insert(job_entry).execute()

        # 5. Local Cleanup
        if os.path.exists(filename):
            os.remove(filename)

        return jsonify({
            "status": "success",
            "job_id": db_response.data[0]['id']
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
