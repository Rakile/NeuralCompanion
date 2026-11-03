FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
RUN pip install --no-cache-dir chess==1.11.2 jsonschema==4.26.0
COPY multiplayer /srv/multiplayer
RUN useradd --uid 10001 --no-create-home chess && mkdir /data && chown chess:chess /data
USER chess
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8767/health', timeout=2)"
CMD ["python", "-B", "-m", "multiplayer", "--private-container-network", "--storage", "/data"]
