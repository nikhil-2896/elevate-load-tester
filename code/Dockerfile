FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/load_tests.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /data load_test_results

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=4).status == 200 else 1)"

# One worker process on purpose: SQLite and the in-process run cap are per
# process. Threads handle concurrent requests. This changes in the Postgres step.
CMD ["gunicorn", "-w", "1", "--threads", "8", "--timeout", "120", "-b", "0.0.0.0:5000", "app:app"]