FROM python:3.10-slim

# Install system dependencies needed for yt-dlp, ffmpeg, and curl-cffi
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    libnss3 \
    libnspr4 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "App.py"]
