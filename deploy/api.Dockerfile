# memory-neo/deploy/api.Dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.api.txt .
RUN pip install --no-cache-dir -r requirements.api.txt

# Copy application code
COPY api/ ./api/
COPY memory_neo/ ./memory_neo/

# Prisma: copy schema and generate client
COPY api/db/schema.prisma ./api/db/schema.prisma
RUN prisma generate --schema=api/db/schema.prisma

EXPOSE 8080

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
