# 1. Use a slim Python image (much faster to deploy)
FROM python:3.9-slim

# 2. Install FFmpeg (Essential for the "Universal" convert-to-mp4 strategy)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 3. Install Python dependencies
# Note: Removed playwright as it's no longer needed for the cookie method
RUN pip install --no-cache-dir \
    flask \
    flask-cors \
    supabase \
    requests \
    yt-dlp

# 4. Copy your app files (including App.py and cookies.txt)
COPY . .

# 5. Environment Variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# 6. Run the app
CMD ["python", "App.py"]
