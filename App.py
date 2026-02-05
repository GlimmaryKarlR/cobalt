import os
import subprocess
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
from playwright.sync_api import sync_playwright

app = Flask(__name__)
CORS(app)

SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") 
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def generate_netscape_cookies():
    print("🍪 Performing deep cookie scrape...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            # Use a real user agent to look less like a bot
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # Go to a specific video instead of home to trigger real session cookies
            page.goto("https://www.youtube.com/watch?v=PdYtVUk-EFo", wait_until="networkidle")
            
            # Give it 5 seconds to settle and run JS
            time.sleep(5) 
            
            raw_cookies = context.cookies()
            lines = ["# Netscape HTTP Cookie File", ""]
            for c in raw_cookies:
                domain = c['domain']
                flag = "TRUE" if domain.startswith('.') else "FALSE"
                path = c['path']
                secure = "TRUE" if c['secure'] else "FALSE"
                # Handle the -1 or missing expiry by setting a far-future date
                expiry = str(int(c.get('expires', time.time() + 86400))) 
                lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{c['name']}\t{c['value']}")
                
            with open("cookies.txt", "w") as f:
                f.write("\n".join(lines))
            browser.close()
            print("✅ Deep cookies saved.")
    except Exception as e:
        print(f"❌ Cookie generation failed: {e}")

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.json
    video_url = data.get('url')
    if not video_url:
        return jsonify({"error": "No URL provided"}), 400

    timestamp = int(time.time() * 1000)
    filename = f"{timestamp}_video.mp4"
    temp_raw = f"raw_{filename}"

    try:
        generate_netscape_cookies()
        
        # We capture stderr to see the ACTUAL error in Koyeb logs
        download_cmd = [
            "yt-dlp",
            "--cookies", "cookies.txt",
            "--match-filter", "duration <= 181",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", temp_raw,
            video_url
        ]
        
        print(f"🎬 Starting download: {video_url}")
        process = subprocess.run(download_cmd, capture_output=True, text=True)
        
        if process.returncode != 0:
            print(f"❌ YT-DLP Error Log:\n{process.stderr}") # CHECK KOYEB LOGS FOR THIS
            return jsonify({"status": "error", "message": f"yt-dlp failed: {process.stderr[:100]}"}), 500

        # Run FFmpeg to fix headers
        print("🛠 Fixing video headers with FFmpeg...")
        ffmpeg_cmd = ["ffmpeg", "-i", temp_raw, "-c", "copy", "-movflags", "+faststart", filename]
        subprocess.run(ffmpeg_cmd, capture_output=True)

        if not os.path.exists(filename):
            return jsonify({"status": "error", "message": "FFmpeg output missing"}), 500

        print(f"📤 Uploading {filename} to Supabase...")
        with open(filename, "rb") as f:
            supabase.storage.from_("videos").upload(filename, f, {"content-type": "video/mp4"})

        job_entry = {
            "video_url": f"videos/{filename}",
            "tier_key": 1,
            "mode": "do",
            "status": "pending",
            "priority": "low",
            "source": "website"
        }
        db_res = supabase.table("jobs").insert(job_entry).execute()

        # Cleanup
        os.remove(filename)
        if os.path.exists(temp_raw): os.remove(temp_raw)

        return jsonify({"status": "success", "job_id": db_res.data[0]['id']})

    except Exception as e:
        print(f"💥 Critical Crash: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
