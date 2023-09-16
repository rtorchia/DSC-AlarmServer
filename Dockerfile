FROM python:3.8-slim-bullseye
WORKDIR /app
ADD . /app
EXPOSE 8111 4025
CMD ["python", "alarmserver.py"]
