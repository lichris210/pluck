FROM python:3.11-slim

# System deps: Node 20 + browser automation prerequisites
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg \
        # Playwright/Camoufox browser deps
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 \
        libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 \
        libasound2 libpangocairo-1.0-0 libpango-1.0-0 \
        fonts-liberation libappindicator3-1 xdg-utils \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps — cached layer, only rebuilds when requirements change
COPY requirements.txt requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-api.txt

# Frontend build — cached layer, only rebuilds when frontend/ changes
COPY frontend/package.json frontend/package-lock.json* ./frontend/
RUN cd frontend && npm ci

COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# Scrapling browser binaries
RUN scrapling install

# App source
COPY . .

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
