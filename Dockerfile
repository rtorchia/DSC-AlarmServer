FROM python:3.8-slim-bullseye
WORKDIR /app
RUN wget  https://github.com/rtorchia/DSC-AlarmServer/archive/refs/heads/main.zip
RUN unzip main.zip
ADD DSC-AlarmServer-main /app
EXPOSE 8111 4025
CMD ["python", "alarmserver.py config=/app/alarmserver.cfg"]
