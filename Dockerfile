FROM python:3.11-slim

# Install system deps for Playwright
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

# Install Playwright and Chromium
RUN pip install playwright
RUN playwright install chromium
RUN playwright install-deps chromium

# This command runs the exporter, then starts your downloader
CMD python exporter.py && python your_main_downloader.py
