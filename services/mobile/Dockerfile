FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY app.py index.html ./
EXPOSE 8094
CMD ["python", "app.py"]
