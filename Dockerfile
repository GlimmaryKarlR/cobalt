# 1. Official Playwright image (v1.58.0 matches the latest pip package)
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

WORKDIR /app

# 2. Pin playwright to 1.58.0 so it matches the image browsers perfectly
RUN pip install --no-cache-dir playwright==1.58.0 flask flask-cors supabase yt-dlp

# 3. Copy your app files
COPY . .

# 4. Environment Variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# 5. Run the app
CMD ["python", "-u", "App.py"]
