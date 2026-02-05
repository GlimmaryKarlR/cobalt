import os
import subprocess
from flask import Flask, request, jsonify
from playwright.sync_api import sync_playwright
from huggingface_hub import HfApi

app = Flask(__name__)

# --- CONFIGURATION (Set these in Koyeb Envs) ---
HF_TOKEN = os.getenv("HF_TOKEN")
REPO_ID = os.getenv("REPO_ID") # e.g., "username/my-video-repo"
HF_API = HfApi()

def get_downr_style_cookies():
    """Replicates the logic from cookie_format.mjs to create a Netscape file."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.youtube.com") # Prime the cookies

        raw_cookies = context.cookies()
        lines = ["# Netscape HTTP Cookie File", "# Generated for Downr-Style Integration", ""]

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

@app.route('/api/process-link', methods=['POST'])
def process_link():
    video_url = request.json.get('url')
    video_id = video_url.split("v=")[-1]
    output_filename = f"{video_id}.mp4"

    try:
        # 1. Generate fresh cookies using extension logic
        get_downr_style_cookies()

        # 2. Download + FastStart Fix (prevents moov atom errors)
        cmd = [
            "yt-dlp", "--cookies", "cookies.txt",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "-o", "raw_video.mp4",
            "--exec", f"ffmpeg -i raw_video.mp4 -c copy -movflags +faststart {output_filename} && rm raw_video.mp4",
            video_url
        ]
        subprocess.run(cmd, check=True)

        # 3. Upload to Hugging Face
        HF_API.upload_file(
            path_or_fileobj=output_filename,
            path_in_repo=f"downloads/{output_filename}",
            repo_id=REPO_ID,
            token=HF_TOKEN
        )

        return jsonify({"status": "success", "file": output_filename})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
