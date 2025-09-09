FROM docker.io/panzhongxian/wecom-bot-svr

RUN python3 -m pip install wecom-bot-svr==0.3.3 dotenv==0.9.9

COPY *.py /data/code/
COPY .env /data/code/.env

CMD ["python3", "/data/code/difybot.py" ]
