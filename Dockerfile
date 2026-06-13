# import python from the docker repo
FROM python:3.13-slim AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        time \
        libreoffice \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# adding a non-root user
RUN groupadd -r appgroup && \
    useradd -r -g appgroup -d /app -s /usr/sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# copy the application source
COPY app/ ./app/
COPY public/ ./public/

# creates the uploads dir
RUN mkdir -p /app/public/uploads

# creates a temporary dir for code evaluation
RUN mkdir -p /tmp/codedu && \
    chown appuser:appgroup /tmp/codedu && \
    chmod 700 /tmp/codedu

# change the ownership (append group)
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8080

# check health provided by nginx
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
CMD python3 -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',8080)); s.send(b'GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n'); d=s.recv(1024); s.close(); exit(0 if b'200' in d else 1)"


CMD ["python3", "-m", "app.main"]
