import os
import uuid
import threading
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from google import genai
from pydantic import BaseModel
from typing import List

app = Flask(__name__)
CORS(app)

# Load API Key from Koyeb Environment Variables
GEMINI_API_KEY = os.environ.get("VITE_GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

# Define the exact structure your Frontend (AnalysisView.tsx) expects
class KeyMoment(BaseModel):
    time: str
    description: str

class VideoAnalysis(BaseModel):
    summary: str
    keyMoments: List[KeyMoment]
    tags: List[str]
    sentiment: str
    engagementScore: int

@app.route('/api/analyze', methods=['POST'])
def analyze_video():
    """Securely analyzes video content using the hidden API key."""
    data = request.json
    video_title = data.get("title")
    context = data.get("context", "")

    prompt = f"""
    Perform a professional AI analysis for a video titled "{video_title}". 
    Additional context: {context}.
    Provide a concise summary, 5 key moments with timestamps, 8 relevant tags, 
    an overall sentiment (e.g. 'Positive'), and an engagement score out of 100.
    """

    try:
        # Generate structured content
        response = client.models.generate_content(
            model='gemini-2.0-flash', # Or your preferred version
            contents=prompt,
            config={
                'response_mime_type': 'application/json',
                'response_schema': VideoAnalysis,
            }
        )
        return response.text # Returns the raw JSON string matching the schema
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ... Keep your existing /api/download and /api/status logic here ...

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
