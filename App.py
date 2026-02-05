import os
import urllib.parse
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Health Check ---
# Koyeb looks for a 200 OK on this path to mark the instance as "Healthy"
@app.route('/', methods=['GET'])
def health_check():
    return "OK", 200

# --- Redirection Logic ---
@app.route('/api/process-link', methods=['POST'])
def process_link():
    """
    Receives a YouTube URL and returns a redirect link to Downr.org
    to bypass server-side bot detection.
    """
    data = request.get_json()
    
    if not data or 'url' not in data:
        return jsonify({"error": "No URL provided"}), 400
    
    video_url = data.get('url')
    
    try:
        # URL encode the video link so it passes correctly in the query string
        encoded_url = urllib.parse.quote(video_url, safe='')
        
        # Construct the Downr referral link
        # Most downloaders use the ?url= or /#url= pattern
        redirect_url = f"https://downr.org/?url={encoded_url}"
        
        print(f"🔄 Redirecting {video_url} to Downr")
        
        return jsonify({
            "status": "redirect",
            "external_url": redirect_url,
            "message": "YouTube processing handled via Downr."
        }), 200
        
    except Exception as e:
        print(f"💥 Error: {str(e)}")
        return jsonify({"error": "Failed to generate redirect"}), 500

if __name__ == "__main__":
    # Koyeb passes the port as an environment variable. 
    # We default to 8080 as requested.
    port = int(os.environ.get("PORT", 8080))
    
    # host='0.0.0.0' is REQUIRED for cloud deployments
    app.run(host="0.0.0.0", port=port)
