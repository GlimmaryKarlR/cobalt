FROM python:3.11-slim

# 1. Install system deps for Playwright, FFmpeg, and networking
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Copy the contents of the current repo (cobalt)
COPY . .

# 3. Install the specific libraries your App.py needs
RUN pip install --no-cache-dir \
    playwright \
    flask \
    flask-cors \
    supabase \
    yt-dlp

# 4. Initialize Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

WORKDIR /app/model_hub_interface/src

# 5. THE CRITICAL PART: 
# If App.py is in this repo, use its path. 
# If you are deploying the 'physVLA' repo in Koyeb instead, use:
CMD ["python", "-u", "App.py"]
