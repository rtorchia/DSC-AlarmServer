# DSC-AlarmServer
Creates web interface to DSC/Envisalink with proxy.

## Quick Setup Instructions:

### Create docker image:
>docker build -t alarmserver .

### Run/Create container:
>docker run -d -p 4025:4025 -p 8111:8111 -e TZ=America/Detroit --restart=always --name alarmserver alarmserver

### Edit alarmserver.cfg in container:
>docker exec -u 0 -it alarmserver /bin/bash
>
>apt update
>
>apt install nano
>
>nano alarmserver.cfg

### Restart container
>docker restart alarmserver
