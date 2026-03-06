FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# Set timezone to New Zealand
ENV TZ=Pacific/Auckland

RUN apt-get update && \
    apt-get install -y --no-install-recommends cron tzdata && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir requests python-dotenv

COPY main.py /app/main.py

# Create a cron file: run at 00:05 every day NZ time
# Log to /var/log/cron.log
RUN printf "5 0 * * * cd /app && /usr/local/bin/python main.py >> /var/log/cron.log 2>&1\n" > /etc/cron.d/spotify-cron && \
    chmod 0644 /etc/cron.d/spotify-cron && \
    crontab /etc/cron.d/spotify-cron

RUN touch /var/log/cron.log

CMD ["cron", "-f"]
