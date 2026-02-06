import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
import yt_dlp
import requests

app = Flask(__name__)
CORS(app)  # Enables cross-origin requests from your Vite frontend

# Securely retrieve the API key from Koyeb Environment Variables
GEMINI_API_KEY = os.environ.get("VITE_GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

@app.route('/api/process-link', methods=['POST'])
def process_link():
    """
    Handles stealth retrieval of video links to extract the direct MP4 URL
    for processing by the AGSI ingestion agent.
    """
    data = request.json
    video_url = data.get('url')
    
    ydl_opts = {
        'format': 'best',
        'noplaylist': True,
        'quiet': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            # In a production scenario, you would trigger your Supabase 
            # processing job here using the direct URL.
            return jsonify({
                "status": "success",
                "title": info.get('title'),
                "job_id": "auto-triggered-backend-job" 
            })
    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 400

@app.route('/api/analyze', methods=['POST'])
def analyze_data():
    """
    Performs secure Gemini analysis on the ingested CSV data.
    """
    data = request.json
    csv_url = data.get('url')
    system_prompt = data.get('system_prompt')

    try:
        # Fetch the CSV content from Supabase storage
        csv_response = requests.get(csv_url)
        csv_text = csv_response.text

        # Securely call Gemini without exposing keys to the browser
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt
            ),
            contents=[f"Here is the kinematic data: \n\n{csv_text}"]
        )
        
        return jsonify({"status": "success", "response": response.text})
    except Exception as e:
        return jsonify({"status": "failed", "error": str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Backend-to-AI chat endpoint for the Formulaic RAG experience.
    """
    data = request.json
    user_message = data.get('message')
    knowledge_base = data.get('knowledge_base', '')
    system_prompt = data.get('system_prompt')

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            config=genai.types.GenerateContentConfig(
                system_instruction=f"{system_prompt}\n\nContext Data: {knowledge_base}"
            ),
            contents=[user_message]
        )
        return jsonify({"response": response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Koyeb provides the PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
