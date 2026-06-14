FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV TZ=Pacific/Auckland

RUN apt-get update && \
    apt-get install -y --no-install-recommends cron tzdata && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir requests

COPY main.py /app/main.py

# Run at 1 minute past every hour
RUN printf "1 * * * * . /etc/environment; cd /app && /usr/local/bin/python main.py >> /proc/1/fd/1 2>&1\n" > /etc/cron.d/spotify-cron && \
    chmod 0644 /etc/cron.d/spotify-cron && \
    crontab /etc/cron.d/spotify-cron

RUN touch /var/log/cron.log

CMD sh -c "printenv > /etc/environment && cron -f"
