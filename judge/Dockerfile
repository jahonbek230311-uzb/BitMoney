FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends g++ gcc openjdk-17-jdk-headless nodejs golang-go rustc ruby php-cli \
    && rm -rf /var/lib/apt/lists/*
COPY sandbox_exec.py /opt/sandbox_exec.py
RUN chmod 755 /opt/sandbox_exec.py
# Build: docker build -t cpjudge-sandbox:latest judge/
