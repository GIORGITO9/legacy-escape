FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/logs /data
EXPOSE 8082
HEALTHCHECK --interval=5s --timeout=3s --retries=20 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8082/health', timeout=2)"
CMD ["python", "-m", "app.main"]
