FROM python:3.11-slim-bullseye
RUN apt-get update
RUN apt-get install -y git
WORKDIR /alarmserver
RUN git clone https://github.com/rtorchia/DSC-AlarmServer.git
RUN apt-get remove -y git
RUN mkdir /alarmserver/config
RUN cp -r DSC-AlarmServer/* .
RUN rm -r DSC-AlarmServer
RUN mv alarmserver.cfg config/
EXPOSE 8111 4025
CMD ["python3", "alarmserver.py", "-c", "/alarmserver/config/alarmserver.cfg"]
