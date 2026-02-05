FROM python:3.11-slim

# 1. Install system dependencies + Node.js
# We combine these to keep the image size smaller.
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    ffmpeg \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Copy your application files
COPY . .

# 3. Install Python packages
# We add 'playwright' here so we can use the CLI in the next step
RUN pip install --no-cache-dir playwright flask flask-cors supabase yt-dlp

# 4. Install Chromium and its OS-level dependencies
# 'install-deps' is a magic command that handles all the Linux libraries
# Chromium needs (libnss, libatk, etc.) so you don't have to list them manually.
RUN playwright install chromium
RUN playwright install-deps chromium

# 5. Set Environment Variables
# Ensures Python output is sent straight to Koyeb logs
ENV PYTHONUNBUFFERED=1
# Tells Playwright where to find the browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/bin

# 6. Run the app
# Using -u makes the logs stream in real-time
CMD ["python", "-u", "App.py"]
