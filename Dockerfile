FROM python:3.8-slim-bullseye
WORKDIR /app
ADD https://https://github.com/rtorchia/DSC-AlarmServer
EXPOSE 8111 4025
CMD ["python", "alarmserver.py config=/app/alarmserver.cfg"]
