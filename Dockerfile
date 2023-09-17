FROM python:3.8-slim-bullseye
RUN apt-get update
RUN apt-get install -y git
WORKDIR /alarmserver
RUN git clone https://github.com/rtorchia/DSC-AlarmServer.git
RUN mkdir config
RUN cp DSC-AlarmServer/alarmserver.cfg config/alarmserver.cfg
EXPOSE 8111 4025
CMD ["python", "/alarmserver/DSC-AlarmServer/alarmserver.py", "-c /alarmserver/config/alarmserver.cfg"]
