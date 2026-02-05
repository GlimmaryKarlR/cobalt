# 1. Use the official Playwright Python image. 
# This already includes Chromium, Firefox, WebKit and all system deps.
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# 2. Set the working directory
WORKDIR /app

# 3. Copy your application code
COPY . .

# 4. Install your Python dependencies
# Note: 'playwright' is already in the base image, but we ensure it matches our version
RUN pip install --no-cache-dir flask flask-cors supabase yt-dlp

# 5. Environment Variables
ENV PYTHONUNBUFFERED=1

# 6. Start the app
# No need to run 'playwright install' - it's already baked into this image!
CMD ["python", "-u", "App.py"]
