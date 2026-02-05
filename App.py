import os
import time
from playwright.sync_api import sync_playwright
from flask import Flask, request, jsonify

app = Flask(__name__)

def automate_downr_capture(youtube_url):
    # This path is where we will store the video temporarily on Koyeb
    save_path = "/tmp/final_video.mp4"
    
    with sync_playwright() as p:
        # Launch browser - headless=True for production
        browser = p.chromium.launch(headless=True)
        # accept_downloads=True is CRITICAL
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        print(f"🚀 Automating Downr for: {youtube_url}")
        page.goto("https://downr.org", wait_until="networkidle")

        # 1. Select the input and paste the URL
        # Selector based on the HTML you provided
        page.fill("input[placeholder='Paste URL here']", youtube_url)

        # 2. Click the Download button
        # Based on your snippet: a button containing 'Download'
        page.click("button:has-text('Download')")

        print("⏳ Waiting for Downr to generate links...")

        # 3. Wait for the '360p' download link to appear
        # We use a wait_for_selector to ensure the server-side processing is done
        page.wait_for_selector("a:has-text('360p')", timeout=60000)

        # 4. Trigger the download and intercept it
        # This prevents the browser from just 'playing' the video
        with page.expect_download() as download_info:
            page.click("a:has-text('360p')")
        
        download = download_info.value
        download.save_as(save_path)
        
        browser.close()
        return save_path

@app.route('/api/process-link', methods=['POST'])
def process_link():
    data = request.json
    video_url = data.get('url')

    if not video_url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        # Execute the automation
        file_location = automate_downr_capture(video_url)
        
        if os.path.exists(file_location):
            print(f"✅ Success! File saved at {file_location}")
            # NEXT STEP: Add your Supabase upload code here
            return jsonify({"status": "success", "local_path": file_location})
        else:
            return jsonify({"error": "File was not saved"}), 500

    except Exception as e:
        print(f"❌ Automation Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
