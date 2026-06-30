FROM python:3.11-slim

LABEL maintainer="VisionWave AI <admin@traidefi.ai>"
LABEL description="Mission Debrief AI — Edge AI auto-debrief for UAV missions"

# System dependencies for OpenCV and ReportLab
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Create output directories
RUN mkdir -p uploads output/pdfs output/frames

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start server
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
