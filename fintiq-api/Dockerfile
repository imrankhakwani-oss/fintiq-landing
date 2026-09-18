FROM python:3.11-slim

WORKDIR /app

# System dependencies needed for some OpenBB providers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# --timeout=300 prevents pip from giving up on large packages like openbb
# --no-cache-dir keeps image size down
COPY requirements.txt .
RUN pip install --no-cache-dir --timeout=300 --upgrade pip && \
    pip install --no-cache-dir --timeout=300 -r requirements.txt

# Copy application
COPY . .

# Railway injects PORT env variable
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
