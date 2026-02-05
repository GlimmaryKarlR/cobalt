import os
import subprocess
import time
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
from playwright.sync_api import sync_playwright

app = Flask(__name__)
CORS(app)

# --- Configuration ---
SUPABASE_URL = "https://wherenftvmhfzhbegftb.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") 
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def generate_netscape_cookies():
    print("🍪 Performing deep 'Human-Sim' cookie scrape...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            
            # Go directly to the video to trigger "Watch" cookies (PO_TOKEN)
            # Using a popular video helps establish a "normal" session
            page.goto("https://www.youtube.com/watch?v=PdYtVUk-EFo", wait_until="domcontentloaded")
            
            # Simulate a human: Wait, then click 'Play' if a button exists, or just wait
            print("⏳ Simulating watch time...")
            time.sleep(8) 
            
            raw_cookies = context.cookies()
            if not raw_cookies:
                return False

            lines = ["# Netscape HTTP Cookie File", ""]
            for c in raw_cookies:
                # Filter out the invalid -1 expires that yt-dlp hates
                expiry = c.get('expires', -1)
                if expiry == -1:
                    expiry = int(time.time() + 3600) # 1 hour from now
                
                domain = c['domain']
                flag = "TRUE" if domain.startswith('.') else "FALSE"
                path = c['path']
                secure = "TRUE" if c['secure'] else "FALSE"
                lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{int(expiry)}\t{c['name']}\t{c['value']}")
                
            with open("cookies.txt", "w") as f:
                f.write("\n".join(lines))
            
            browser.close()
            print("✅ Watch-session cookies saved.")
            return True
    except Exception as e:
        print(f"❌ Cookie generation failed: {e}")
        return False

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
        # 1. Try to get cookies
        has_cookies = generate_netscape_cookies()
        
        # 2. Build yt-dlp command
        download_cmd = [
            "yt-dlp",
            "--no-check-certificates",
            "--user-agent", USER_AGENT,
            "--match-filter", "duration <= 181",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", temp_raw,
            video_url
        ]

        # Use cookies only if they were successfully generated
        if has_cookies and os.path.exists("cookies.txt"):
            download_cmd.insert(1, "--cookies")
            download_cmd.insert(2, "cookies.txt")
        
        print(f"🎬 Starting download: {video_url}")
        process = subprocess.run(download_cmd, capture_output=True, text=True)
        
        if process.returncode != 0:
            print(f"❌ YT-DLP Error Log:\n{process.stderr}")
            return jsonify({
                "status": "error", 
                "message": f"yt-dlp failed. Bot detection likely. Check Koyeb logs."
            }), 500

        # 3. Fix headers with FFmpeg
        if os.path.exists(temp_raw):
            print("🛠 Fixing video headers with FFmpeg...")
            ffmpeg_cmd = ["ffmpeg", "-i", temp_raw, "-c", "copy", "-movflags", "+faststart", filename]
            subprocess.run(ffmpeg_cmd, capture_output=True)
        else:
            return jsonify({"status": "error", "message": "Download completed but file not found."}), 500

        # 4. Upload to Supabase Storage
        print(f"📤 Uploading {filename} to Supabase...")
        with open(filename, "rb") as f:
            supabase.storage.from_("videos").upload(filename, f, {"content-type": "video/mp4"})

        # 5. Insert Job into Database
        job_entry = {
            "video_url": f"videos/{filename}",
            "tier_key": 1,
            "mode": "do",
            "status": "pending",
            "priority": "low",
            "source": "website"
        }
        db_res = supabase.table("jobs").insert(job_entry).execute()

        # 6. Cleanup local files
        if os.path.exists(filename): os.remove(filename)
        if os.path.exists(temp_raw): os.remove(temp_raw)
        if os.path.exists("cookies.txt"): os.remove("cookies.txt")

        return jsonify({"status": "success", "job_id": db_res.data[0]['id']})

    except Exception as e:
        print(f"💥 Critical Crash: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/', methods=['GET'])
def health_check():
    return "Server is running. Endpoint: /api/process-link", 200

if __name__ == "__main__":
    # Koyeb expects 0.0.0.0 to route traffic correctly
    app.run(host="0.0.0.0", port=8080)
