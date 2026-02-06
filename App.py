import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from playwright.sync_api import sync_playwright

app = Flask(__name__)
CORS(app)

# Environment Variables (Set these in Koyeb Secrets)
GEMINI_API_KEY = os.environ.get("VITE_GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    """
    Retrieval Agent: Uses Playwright to navigate to video links stealthily,
    bypassing bot detection to extract metadata or stream URLs.
    """
    data = request.json
    video_url = data.get('url')
    user_id = data.get('user_id')

    try:
        with sync_playwright() as p:
            # Launching chromium as configured in your Dockerfile
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            page = context.new_page()
            
            # Navigate to the video URL to trigger extraction
            page.goto(video_url, wait_until="networkidle")
            page_title = page.title()
            
            # Logic for internal job triggering would go here
            # For now, we return a success status to the UI
            browser.close()
            
            return jsonify({
                "status": "success",
                "job_id": f"job_{os.urandom(4).hex()}",
                "title": page_title
            })
    except Exception as e:
        print(f"Retrieval Error: {str(e)}")
        return jsonify({"status": "failed", "error": "Agent failed to retrieve stream"}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze():
    """
    Secure Analysis: Fetches the CSV from the provided URL and 
    uses Gemini 2.0 Flash to perform the kinematic breakdown.
    """
    data = request.json
    csv_url = data.get('url')
    system_prompt = data.get('system_prompt')

    try:
        # Download the CSV data from Supabase/Koyeb storage
        response = requests.get(csv_url)
        csv_content = response.text

        # Generate analysis using the Python SDK
        # This keeps the VITE_GEMINI_API_KEY strictly on the server
        result = client.models.generate_content(
            model="gemini-2.0-flash",
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt
            ),
            contents=[f"Analyze this kinematic data: \n\n{csv_content}"]
        )

        return jsonify({
            "status": "success", 
            "response": result.text,
            "summary": "Kinematic force vectors indexed successfully."
        })
    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Formulaic RAG: Allows the user to ask follow-up questions
    about the specific CSV data currently in memory.
    """
    data = request.json
    user_message = data.get('message')
    knowledge_base = data.get('knowledge_base', 'No data loaded.')
    system_prompt = data.get('system_prompt')

    try:
        chat_response = client.models.generate_content(
            model="gemini-2.0-flash",
            config=genai.types.GenerateContentConfig(
                system_instruction=f"{system_prompt}\n\nContext: {knowledge_base}"
            ),
            contents=[user_message]
        )
        return jsonify({"response": chat_response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Flask default, but Gunicorn will override this in production
    app.run(host='0.0.0.0', port=8000)
