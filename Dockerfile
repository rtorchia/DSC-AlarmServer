FROM python:3.12-slim-bullseye
WORKDIR /app
ADD . /app
EXPOSE 8111 4025
CMD ["python", "alarmserver.py"]

