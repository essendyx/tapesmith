FROM python:3.12-slim

RUN useradd --create-home --uid 1000 shortlink

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shortlink.py .

RUN mkdir -p /data && chown shortlink:shortlink /data
VOLUME /data

USER shortlink

ENV SHORTLINK_PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["sh", "-c", "uvicorn shortlink:factory --factory --host 0.0.0.0 --port ${SHORTLINK_PORT}"]
