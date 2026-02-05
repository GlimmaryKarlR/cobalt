FROM python:3.11-slim

# Install system deps + Node.js (for yt-dlp JavaScript runtime)
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2 ffmpeg curl \
    gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir playwright flask flask-cors supabase yt-dlp
RUN playwright install chromium
RUN playwright install-deps chromium

CMD ["python", "-u", "App.py"]
