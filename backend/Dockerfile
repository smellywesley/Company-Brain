FROM python:3.12-slim

# Create non‑root user
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app

# Install system deps (git, curl) only if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Audit chain (AuditLogMiddleware) writes logs/audit.jsonl — the dir must be
# writable by the non-root user or every audit write dies with EACCES (seen as
# repeated PermissionError in the live CI run's backend logs).
RUN mkdir -p /app/logs && chown -R appuser:appgroup /app/logs

# Switch to non‑root user
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
