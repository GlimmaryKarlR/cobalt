# 1. Use the official Playwright image which includes Python and all browser dependencies
# Noble is Ubuntu 24.04, which is very stable for 2026 deployments
FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

# 2. Set environment variables to ensure Python output is logged immediately
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 3. Set the working directory
WORKDIR /app

# 4. Install system-level tools (ffmpeg is still needed for merging video/audio)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 5. Copy requirements and install Python libraries
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Pre-install ONLY the Chromium browser (to save space/time)
# This ensures the "Agent" has its browser ready to go
RUN playwright install chromium

# 7. Copy the rest of your application code
COPY . .

# 8. Expose the port your Flask app runs on
EXPOSE 8000

# 9. Start the application
CMD ["python", "App.py"]
