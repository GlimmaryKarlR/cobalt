FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2 ffmpeg curl \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir playwright flask flask-cors supabase yt-dlp

RUN playwright install chromium
RUN playwright install-deps chromium

CMD ["python", "-u", "App.py"]
