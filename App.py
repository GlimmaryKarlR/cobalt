import os
import uuid
import threading
import traceback
import tempfile
import time
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp
from playwright.sync_api import sync_playwright
# Corrected import for 2026 version of playwright-stealth
from playwright_stealth import Stealth

app = Flask(__name__)
CORS(app)

# Ensure download directory exists
DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Global dictionary to track job statuses
jobs = {}

def get_stealth_session(video_url):
    """
    The 'AI Agent' logic: Uses a headless browser to mimic human activity, 
    satisfy YouTube's BotGuard, and capture a validated session.
    """
    print(f"🤖 [Agent] Starting stealth warm-up for: {video_url}")
    
    # Create a unique cookie file for this specific session
    cookie_file = os.path.join(DOWNLOAD_DIR, f"cookies_{uuid.uuid4()}.txt")
    
    with sync_playwright() as p:
        # Launch with Docker/Koyeb safety flags
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        # Apply the new class-based stealth evasions
        stealth = Stealth()
        page = context.new_page()
        stealth.apply_stealth_sync(page) 

        try:
            # 1. Trigger the security handshake by visiting a YouTube embed
            page.goto("https://www.youtube.com/embed/aqz-KE-bpKQ", wait_until="networkidle", timeout=60000)
            
            # 2. Mimic human dwell time
            page.wait_for_timeout(3500)
            
            # 3. Extract verified cookies
            cookies = context.cookies()
            visitor_data = next((c['value'] for c in cookies if c['name'] == 'VISITOR_INFO1_LIVE'), "")

            # 4. Generate Netscape-formatted cookie file for yt-dlp compatibility
            with open(cookie_file, "w") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for c in cookies:
                    domain = c['domain']
                    if not domain.startswith('.') and not domain.startswith('http'):
                        domain = f".{domain}"
                    
                    secure = "TRUE" if c['secure'] else "FALSE"
                    expires = int(c.get('expires', 0))
                    path = c['path']
                    name = c['name']
                    value = c['value']
                    
                    # Netscape format: domain, flag, path, secure, expiration, name, value
                    f.write(f"{domain}\tTRUE\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
            
            print(f"✅ [Agent] Handshake successful. VisitorData: {visitor_data[:10]}...")
            return visitor_data, cookie_file
            
        except Exception as e:
            print(f"❌ [Agent] Handshake failed: {str(e)}")
            return None, None
        finally:
            browser.close()

def auto_cleanup(filepath, delay=600):
    """Deletes the downloaded video after X seconds to save Koyeb disk space."""
    time.sleep(delay)
    if os.path.exists(filepath):
        os.remove(filepath)
        print(f"🧹 [Cleanup] Deleted temporary file: {filepath}")

def download_task(job_id, video_url):
    try:
        jobs[job_id].update({"status": "processing", "current_step": "AI Agent: Authenticating"})
        
        # We now run EVERYTHING inside one browser context
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36")
            stealth = Stealth()
            page = context.new_page()
            stealth.apply_stealth_sync(page)

            # 1. Warm up the session
            page.goto("https://www.youtube.com/embed/aqz-KE-bpKQ", wait_until="networkidle")
            page.wait_for_timeout(4000)
            
            # 2. Extract tokens while browser is LIVE
            cookies = context.cookies()
            visitor_data = next((c['value'] for c in cookies if c['name'] == 'VISITOR_INFO1_LIVE'), "")
            
            # Create the cookie file
            cookie_path = os.path.join(DOWNLOAD_DIR, f"cookies_{job_id}.txt")
            with open(cookie_path, "w") as f:
                f.write("# Netscape HTTP Cookie File\n")
                for c in cookies:
                    domain = c['domain'] if c['domain'].startswith('.') else f".{c['domain']}"
                    f.write(f"{domain}\tTRUE\t{c['path']}\t{'TRUE' if c['secure'] else 'FALSE'}\t{int(c.get('expires', 2147483647))}\t{c['name']}\t{c['value']}\n")

            # 3. Download IMMEDIATELY while browser session is active
            local_filename = f"{job_id}.mp4"
            local_path = os.path.join(DOWNLOAD_DIR, local_filename)
            
            ydl_opts = {
                'format': 'best',
                'outtmpl': local_path,
                'cookiefile': cookie_path,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['web'],
                        'visitor_data': visitor_data,
                        # Adding the 'po_token' requirement
                        'po_token': 'web+MlOIBQ-9cxO2dIg5E1pbitCc9EmKvr-zQ_FP5A3LiruxAWph5vqcYKlntiDwm9Eqlm_fUEczErbBZAWhAGewsEWWZnQOWWdsWimI16DH1U8dcNYX-Q=='
                    }
                },
            }

            jobs[job_id]["current_step"] = "Downloading"
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            browser.close() # Now we close it

        jobs[job_id].update({"status": "completed", "progress_percent": 100, "result_url": f"/download/{local_filename}"})

    except Exception as e:
        print(f"🚨 Error: {traceback.format_exc()}")
        jobs[job_id].update({"status": "failed", "error_message": str(e)})

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
        "progress_percent": 5,
        "current_step": "Initializing Agent"
    }

    threading.Thread(target=download_task, args=(job_id, url)).start()
    return jsonify(jobs[job_id])

@app.route('/api/job-status/<job_id>')
def get_status(job_id):
    return jsonify(jobs.get(job_id, {"error": "Job not found"}))

@app.route('/download/<filename>')
def serve_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename)

if __name__ == '__main__':
    # Koyeb default port is 8000
    app.run(host='0.0.0.0', port=8080)
