FROM python:3.12-slim

# ffmpeg нужен video-bot-у для yt-dlp merge (когда видео из отдельных потоков).
# для hub / research_bot — лишний вес, но он минимальный (~70 MB).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# зависимости отдельным слоем — кешируется между билдами кода
COPY src/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# исходники
COPY src/ /app/

# persistent data (db.sqlite3) монтируется как volume в compose
VOLUME ["/app/data"]
ENV SQLITE_PATH=/app/data/db.sqlite3

# webhook порт по умолчанию
EXPOSE 8080

# CMD переопределяется в docker-compose:
#   muagent-hub      → python bot.py
#   muagent-research → python research_bot.py
CMD ["python", "bot.py"]
