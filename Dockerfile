# 1. Official Playwright image
FROM mcr.microsoft.com/playwright/python:v1.48.0-noble

WORKDIR /app

# 2. Install dependencies (Added 'requests' here)
RUN pip install --no-cache-dir \
    playwright==1.48.0 \
    flask \
    flask-cors \
    supabase \
    requests \
    yt-dlp

# 3. Ensure the browsers are fully installed and dependencies met
RUN playwright install chromium
RUN playwright install-deps chromium

# 4. Copy your app files
COPY . .

# 5. Environment Variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# 6. Run the app (using python3 to be safe)
CMD ["python3", "-u", "App.py"]
