FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ ./backend/
COPY --from=frontend /app/frontend/dist ./frontend/dist
RUN useradd --create-home uita && mkdir /data && chown uita:uita /data
USER uita
ENV PYTHONPATH=/app/backend DATABASE_URL=sqlite:////data/uita.db CRUSOE_BUDGET_DB=/data/inference-ledger.sqlite3
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/api/health')"
CMD ["uvicorn","uita.app:app","--host","0.0.0.0","--port","8001","--workers","1"]
