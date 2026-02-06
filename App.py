import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from playwright.sync_api import sync_playwright

app = Flask(__name__)
# Update CORS to allow your frontend origin if needed, or leave as * for development
CORS(app)

# Environment Variables (Set these in Koyeb Secrets)
GEMINI_API_KEY = os.environ.get("VITE_GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    """
    Retrieval Agent: Uses Playwright to navigate to video links stealthily.
    """
    data = request.json
    video_url = data.get('url')

    try:
        with sync_playwright() as p:
            # Dockerfile already installed chromium, so we just launch it
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # Navigate and extract
            page.goto(video_url, wait_until="networkidle", timeout=60000)
            page_title = page.title()
            
            # Close browser immediately after extraction
            browser.close()
            
            return jsonify({
                "status": "success",
                "job_id": f"job_{os.urandom(4).hex()}",
                "title": page_title
            })
    except Exception as e:
        print(f"Retrieval Error: {str(e)}")
        return jsonify({"status": "failed", "error": str(e)}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze():
    """
    Analysis Agent: Securely processes CSV data using Gemini 2.0 Flash.
    """
    data = request.json
    csv_url = data.get('url')
    system_prompt = data.get('system_prompt')

    try:
        # Download the CSV content from the result_url
        response = requests.get(csv_url, timeout=30)
        csv_content = response.text

        # Call Gemini securely
        result = client.models.generate_content(
            model="gemini-2.0-flash",
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt
            ),
            contents=[f"CONTEXTUAL DATASET:\n\n{csv_content}"]
        )

        return jsonify({
            "status": "success", 
            "response": result.text,
            "summary": "Geospatial physics analysis completed."
        })
    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Formulaic RAG: User consultation endpoint.
    """
    data = request.json
    user_message = data.get('message')
    knowledge_base = data.get('knowledge_base', '')
    system_prompt = data.get('system_prompt')

    try:
        chat_response = client.models.generate_content(
            model="gemini-2.0-flash",
            config=genai.types.GenerateContentConfig(
                system_instruction=f"{system_prompt}\n\n[DATABASE CONTEXT]\n{knowledge_base}"
            ),
            contents=[user_message]
        )
        return jsonify({"response": chat_response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Koyeb 2026 default port 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
