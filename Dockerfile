FROM node:26-bookworm-slim AS web
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY . .
RUN npm run build:local

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend WEB_DIR=/app/dist-local
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt && useradd --uid 10001 --create-home pablo
COPY backend backend
COPY --from=web /app/dist-local ./dist-local
USER pablo
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "pablo.main:app", "--host", "0.0.0.0", "--port", "8000"]
