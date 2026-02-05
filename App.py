import os
import subprocess
import json
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/api/get-redirect', methods=['POST'])
def get_redirect():
    data = request.json
    video_url = data.get('url')
    
    # We use specific Android/iOS clients to bypass the "Bot" check
    # This mimics the params in the URL you provided (c=ANDROID)
    cmd = [
        "yt-dlp",
        "--get-url",
        "--no-check-certificates",
        "--extractor-args", "youtube:player_client=android,ios", 
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        video_url
    ]

    try:
        print(f"🔗 Fetching direct redirect for: {video_url}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            print(f"❌ Failed: {result.stderr}")
            return jsonify({"error": "YouTube blocked the request. Try again."}), 500

        # yt-dlp returns the direct googlevideo.com URLs
        urls = result.stdout.strip().split('\n')
        
        return jsonify({
            "status": "success",
            "download_url": urls[0], # This is the link like the one you shared
            "note": "This link is IP-bound. It must be opened by the same IP that requested it."
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
