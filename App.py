import os
import uuid
import threading
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

app = Flask(__name__)
CORS(app)

# Storage for job status
jobs = {}

def get_stealth_tokens(video_url):
    """
    The 'Agent' process: Opens a real browser to fetch human-validated tokens.
    """
    print("🤖 Agent: Opening stealth browser...")
    with sync_playwright() as p:
        # Launch headless browser
        browser = p.chromium.launch(headless=True)
        # Use a real-looking User Agent
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        stealth_sync(page) # Hide automation signatures

        # Navigate to a generic YouTube page first to establish cookies
        page.goto("https://www.youtube.com/embed/aqz-KE-bpKQ", wait_until="networkidle")
        
        # Extract Visitor Data from the browser's cookies/context
        cookies = context.cookies()
        visitor_data = None
        for cookie in cookies:
            if cookie['name'] == 'VISITOR_INFO1_LIVE':
                visitor_data = cookie['value']
        
        # Note: In a production 'Agent', you could also scrape the 'poToken' 
        # from network requests here, but visitor_data is the start.
        
        browser.close()
        return visitor_data, cookies

def download_task(job_id, video_url):
    try:
        jobs[job_id]["status"] = "processing"
        jobs[job_id]["current_step"] = "AI Agent Authenticating"

        # 1. RUN THE AGENT
        visitor_data, stealth_cookies = get_stealth_tokens(video_url)
        
        # 2. CONFIGURE YT-DLP WITH AGENT DATA
        local_filename = f"{job_id}.mp4"
        ydl_opts = {
            'format': 'best',
            'outtmpl': local_filename,
            'quiet': False,
            'no_warnings': False,
            # We pass the 'Human' data we just grabbed
            'extractor_args': {
                'youtube': {
                    'player_client': ['web'],
                    'visitor_data': visitor_data if visitor_data else ""
                }
            },
        }

        print(f"🧵 [Job {job_id}] Agent handshake complete. Starting download...")
        jobs[job_id]["current_step"] = "Downloading Video"
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["progress_percent"] = 100
        jobs[job_id]["result_url"] = f"https://your-app.koyeb.app/download/{local_filename}"

    except Exception as e:
        print(f"❌ Failure in Job {job_id}: {traceback.format_exc()}")
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error_message"] = str(e)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.json
    video_url = data.get("url")
    if not video_url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "id": job_id,
        "status": "pending",
        "progress_percent": 5,
        "current_step": "Initializing Agent"
    }

    thread = threading.Thread(target=download_task, args=(job_id, video_url))
    thread.start()

    return jsonify(jobs[job_id])

@app.route('/api/job-status/<job_id>')
def get_status(job_id):
    return jsonify(jobs.get(job_id, {"error": "Job not found"}))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
