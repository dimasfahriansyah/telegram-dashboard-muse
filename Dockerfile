FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py status.py reporter.py ./

# status.json disimpan di volume supaya tidak hilang saat container restart.
# Jalankan dengan: docker run -d --env-file .env -v muse-status:/app/data \
#   -e STATUS_FILE=/app/data/status.json -p 8080:8080 muse-dashboard
VOLUME ["/app/data"]

EXPOSE 8080
CMD ["python", "bot.py"]
