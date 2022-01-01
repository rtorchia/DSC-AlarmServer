FROM python:3.8
WORKDIR /app
ADD . /app
EXPOSE 8111 4025
CMD ["python", "alarmserver.py"]