import os
import uuid
import threading
import traceback
import tempfile
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

app = Flask(__name__)
CORS(app)

# Directory to store downloads temporarily
DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Global job tracking
jobs = {}

def get_stealth_session(video_url):
    """
    Agent Logic: Opens a browser, mimics a human to bypass BotGuard,
    and returns Netscape cookies + Visitor Data.
    """
    print(f"🤖 [Agent] Warming up session for: {video_url}")
    
    # Create a unique temp file for this job's cookies
    cookie_file = os.path.join(DOWNLOAD_DIR, f"cookies_{uuid.uuid4()}.txt")
    
    with sync_playwright() as p:
        # Launch with Docker-safe flags
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        page = context.new_page()
        stealth_sync(page) # Mask Playwright signatures

        try:
            # Navigate to YouTube (using embed is faster and triggers less anti-bot)
            page.goto("https://www.youtube.com/embed/aqz-KE-bpKQ", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000) # Human-like pause
            
            cookies = context.cookies()
            visitor_data = next((c['value'] for c in cookies if c['name'] == 'VISITOR_INFO1_LIVE'), "")

            # Convert JSON cookies to Netscape format for yt-dlp
            with open(cookie_file, "w") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for c in cookies:
                    domain = c['domain']
                    # Ensure domain starts with a dot if it's a subdomain
                    if not domain.startswith('.') and not domain.startswith('http'):
                        domain = f".{domain}"
                    
                    secure = "TRUE" if c['secure'] else "FALSE"
                    expires = int(c.get('expires', 0))
                    path = c['path']
                    name = c['name']
                    value = c['value']
                    
                    # Format: domain, flag, path, secure, expiration, name, value
                    f.write(f"{domain}\tTRUE\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
            
            print(f"✅ [Agent] Handshake successful. VisitorData: {visitor_data[:8]}...")
            return visitor_data, cookie_file
            
        except Exception as e:
            print(f"❌ [Agent] Failed to get session: {str(e)}")
            return None, None
        finally:
            browser.close()

def download_task(job_id, video_url):
    cookie_path = None
    try:
        jobs[job_id].update({"status": "processing", "current_step": "AI Agent: Authenticating"})
        
        # 1. Start the Stealth Agent
        visitor_data, cookie_path = get_stealth_session(video_url)
        
        if not cookie_path:
            raise Exception("Agent failed to secure a valid YouTube session.")

        # 2. Configure yt-dlp with the Agent's credentials
        local_filename = f"{job_id}.mp4"
        local_path = os.path.join(DOWNLOAD_DIR, local_filename)
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': local_path,
            'cookiefile': cookie_path,
            'verbose': True, # Logs more info to Koyeb console
            'extractor_args': {
                'youtube': {
                    'player_client': ['web'],
                    'visitor_data': visitor_data
                }
            },
        }

        jobs[job_id]["current_step"] = "Downloading Streams"
        print(f"🧵 [Job {job_id}] Transferring session to yt-dlp...")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        jobs[job_id].update({
            "status": "completed",
            "progress_percent": 100,
            "result_url": f"/download/{local_filename}"
        })

    except Exception as e:
        print(f"🚨 Job {job_id} Error: {traceback.format_exc()}")
        jobs[job_id].update({
            "status": "failed",
            "error_message": str(e)
        })
    finally:
        # Cleanup cookie file immediately to save space
        if cookie_path and os.path.exists(cookie_path):
            os.remove(cookie_path)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.json
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing URL"}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "id": job_id,
        "status": "pending",
        "progress_percent": 10,
        "current_step": "Agent Spawning"
    }

    threading.Thread(target=download_task, args=(job_id, url)).start()
    return jsonify(jobs[job_id])

@app.route('/api/job-status/<job_id>')
def get_status(job_id):
    return jsonify(jobs.get(job_id, {"error": "Not found"}))

@app.route('/download/<filename>')
def serve_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename)

if __name__ == '__main__':
    # Koyeb requires port 8000 by default in most templates
    app.run(host='0.0.0.0', port=8000)
