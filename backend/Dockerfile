FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gcc \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
# PyTorch CPU: 2.4.1+cpu has no aarch64 wheel; 2.6.0+cpu is the earliest +cpu on arm64
RUN pip install --no-cache-dir \
    torch==2.6.0+cpu \
    --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# start.sh must be executable; chmod as root before switching user
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Production: run migrations then uvicorn. docker-compose overrides with: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
CMD ["/app/start.sh"]
