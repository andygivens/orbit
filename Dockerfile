# Build frontend assets
FROM node:22-bookworm AS ui-build
WORKDIR /ui

COPY ui/package.json ui/package-lock.json ./
# Install dependencies; npm caches in layer for faster rebuilds
RUN npm ci

COPY ui .
RUN npm run build

# Runtime image
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    vim \
    make \
    && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY . /app/

# Install Python dependencies (including dev extras for testing/linting)
RUN pip install --no-cache-dir -e .[dev]

# Copy built frontend assets into application static directory
COPY --from=ui-build /ui/dist /app/app/static/ui

# Environment configuration
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Default command for development
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--reload"]
