FROM python:3.8-slim-bullseye
WORKDIR /app
ADD https://api.github.com/repos/rtorchia/DSC-AlarmServer/tarball/master
EXPOSE 8111 4025
CMD ["python", "alarmserver.py config=/app/alarmserver.cfg"]
