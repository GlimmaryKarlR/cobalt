# 1. Official Playwright image (includes Chromium + System Deps)
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# 2. Install the Playwright Python library (this fixes the ModuleNotFoundError)
# We also include your other requirements.
RUN pip install --no-cache-dir playwright flask flask-cors supabase yt-dlp

# 3. Copy your app files
COPY . .

# 4. Set Environment Variables
ENV PYTHONUNBUFFERED=1
# Koyeb sets PORT automatically, but we default to 8080 just in case
ENV PORT=8080

# 5. Run the app
CMD ["python", "-u", "App.py"]
