FROM python:3.11-slim

# 1. Install system deps for Playwright, FFmpeg, and networking
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# 2. Set the working directory
WORKDIR /app

# 3. Copy the current folder (cobalt) into /app
COPY . .

# 4. Install specific libraries
RUN pip install --no-cache-dir \
    playwright \
    flask \
    flask-cors \
    supabase \
    yt-dlp

# 5. Initialize Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

# 6. Run the app directly from the current folder
# Since App.py is now in the root of the repo, this will find it immediately.
CMD ["python", "-u", "App.py"]
