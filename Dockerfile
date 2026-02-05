FROM python:3.11-slim

# 1. Install system deps for Playwright, FFmpeg, and networking
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Copy your entire repository into the container
COPY . .

# 3. Install Python dependencies directly
# We add flask-cors for frontend communication and supabase for the jobs table
RUN pip install --no-cache-dir \
    playwright \
    flask \
    flask-cors \
    supabase \
    yt-dlp

# 4. Initialize Playwright browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# 5. Run the app
# Based on your directory: model_hub_interface/src/App.py
# We use -u for unbuffered logs so you can see them in Koyeb
CMD ["python", "-u", "model_hub_interface/src/App.py"]
