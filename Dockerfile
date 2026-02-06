# 1. Use Python 3.10 (3.9 is deprecated and struggles with curl_cffi)
FROM python:3.10-slim

# 2. Install FFmpeg and build essentials for curl_cffi
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 3. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy your app files
COPY . .

# 5. Environment Variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# 6. Run the app
CMD ["python", "App.py"]
