import os
import uuid
import threading
import traceback
import time
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

app = Flask(__name__)
# CORS_WILDCARD = 1 logic
CORS(app)

DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# Dictionary to store BackendJobStatus objects
jobs = {}

def get_stealth_session():
    """Spawns an agent to get fresh cookies and visitor data."""
    with sync_playwright() as p:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent=user_agent)
        stealth = Stealth()
        page = context.new_page()
        stealth.apply_stealth_sync(page)

        try:
            page.goto("https://www.youtube.com", wait_until="networkidle")
            page.wait_for_timeout(3000)
            cookies = context.cookies()
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            visitor_data = next((c['value'] for c in cookies if c['name'] == 'VISITOR_INFO1_LIVE'), "")
            return user_agent, cookie_str, visitor_data
        finally:
            browser.close()

def download_task(job_id, video_url):
    """The background worker that updates the status for App.tsx polling."""
    try:
        # Step 1: Identity Handshake
        jobs[job_id].update({"status": "processing", "current_step": "Agent: Mimicking Browser", "progress_percent": 15})
        ua, cookies, visitor = get_stealth_session()

        # Step 2: Stream Retrieval
        jobs[job_id].update({"current_step": "Retrieving Video Stream...", "progress_percent": 40})
        local_filename = f"{job_id}.mp4"
        local_path = os.path.join(DOWNLOAD_DIR, local_filename)

        ydl_opts = {
            'format': 'best',
            'outtmpl': local_path,
            'user_agent': ua,
            'http_headers': {
                'Cookie': cookies,
                'Referer': 'https://www.google.com/',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['web_embedded'],
                    'visitor_data': visitor
                }
            }
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            jobs[job_id].update({"current_step": "Saving to Local Cache...", "progress_percent": 70})
            ydl.download([video_url])

        # Step 3: Completion
        # result_url matches the path App.tsx uses to build the download link
        jobs[job_id].update({
            "status": "completed",
            "progress_percent": 100,
            "result_url": f"/download/{local_filename}"
        })

    except Exception as e:
        print(f"🚨 Job {job_id} Error: {traceback.format_exc()}")
        jobs[job_id].update({"status": "failed", "error_message": str(e)})

@app.route('/api/download', methods=['POST'])
def start_download():
    """Endpoint called by startJob in App.tsx"""
    data = request.json
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing URL"}), 400

    job_id = str(uuid.uuid4())
    # Initialize with pending status as expected by BackendJobStatus interface
    jobs[job_id] = {
        "status": "pending",
        "progress_percent": 5,
        "current_step": "Initializing session..."
    }

    threading.Thread(target=download_task, args=(job_id, url)).start()
    return jsonify({"job_id": job_id})

@app.route('/api/status/<job_id>')
def get_status(job_id):
    """Endpoint called by pollJobStatus in App.tsx"""
    return jsonify(jobs.get(job_id, {"status": "failed", "error_message": "Job ID not found"}))

@app.route('/download/<filename>')
def serve_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename)

if __name__ == '__main__':
    # Koyeb-ready port binding
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
