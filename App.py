import os
import uuid
import threading
import traceback
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import yt_dlp
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

app = Flask(__name__)
CORS(app)

DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

jobs = {}

def download_task(job_id, video_url):
    try:
        jobs[job_id].update({"status": "processing", "current_step": "Agent: Mimicking Browser"})
        
        with sync_playwright() as p:
            # 1. Launch Agent with a specific, consistent User Agent
            user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(user_agent=user_agent)
            stealth = Stealth()
            page = context.new_page()
            stealth.apply_stealth_sync(page)

            # 2. Visit YouTube and wait for the "Challenge" to pass
            page.goto("https://www.youtube.com", wait_until="networkidle")
            page.wait_for_timeout(3000)
            
            # 3. Extract cookies and format them into a SINGLE string for the Header
            cookies = context.cookies()
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            
            # 4. Configure yt-dlp to use the AGENT'S identity
            local_filename = f"{job_id}.mp4"
            local_path = os.path.join(DOWNLOAD_DIR, local_filename)
            
            ydl_opts = {
                'format': 'best',
                'outtmpl': local_path,
                'nocheckcertificate': True,
                # This mimics the --user-agent and --add-header cookies from the FAQ
                'user_agent': user_agent,
                'http_headers': {
                    'Cookie': cookie_str,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Referer': 'https://www.google.com/',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['web_embedded'], # Use embedded client to bypass standard bot checks
                    }
                },
            }

            jobs[job_id]["current_step"] = "Downloading"
            print(f"🧵 [Job {job_id}] Identity spoofing active. Starting stream...")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            browser.close()

        jobs[job_id].update({"status": "completed", "progress_percent": 100, "result_url": f"/download/{local_filename}"})

    except Exception as e:
        print(f"🚨 Integration Error: {traceback.format_exc()}")
        jobs[job_id].update({"status": "failed", "error_message": str(e)})
