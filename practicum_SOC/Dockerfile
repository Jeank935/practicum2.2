FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home soc
COPY src/ src/
COPY config/ config/
COPY templates/ templates/
COPY static/ static/
RUN mkdir -p analysis && chown -R soc:soc /app/analysis
USER soc
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "web_app:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
