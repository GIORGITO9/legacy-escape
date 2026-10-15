FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir pytest==8.3.3 psycopg2-binary==2.9.10
WORKDIR /tests
COPY . .
CMD ["pytest", "-v", "-p", "no:cacheprovider", "--junitxml=/results/junit.xml"]
