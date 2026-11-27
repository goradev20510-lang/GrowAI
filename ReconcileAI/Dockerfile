FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr curl \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PORT=8501

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home --uid 1000 app && mkdir -p database data/processed data/uploads backups \
 && chown -R app:app /app
USER app

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS "http://localhost:${PORT}$([ "$APP_MODE" = api ] && echo /api/health || echo /_stcore/health)" || exit 1
# APP_MODE=api serves the FastAPI backend (for the React frontend); the default is Streamlit.
CMD if [ "$APP_MODE" = api ]; then exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT}; \
    else exec streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true; fi
