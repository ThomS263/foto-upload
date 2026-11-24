FROM python:3.12-slim AS store
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY foto_upload/ ./foto_upload/
COPY LICENSE .
ENV PHOTO_DATA_DIR=/data PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp XDG_CACHE_HOME=/tmp/.cache
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=4s --start-period=20s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health?ready=1', timeout=3).close()"]
ENTRYPOINT ["python", "-m", "foto_upload.serve"]

CMD ["foto_upload:create_app()"]
