# DSC-AlarmServer
Creates web interface to DSC/Envisalink with proxy.
Since the Envisalink module can only have one connection, this phython script can create a proxy so that multiple connections can be used.

See **alarmserver.cfg** file for instructions on customizing.


Default web address is http://\<server ip address\>:8111

## Quick Setup Instructions for Docker:

### 1. Download repository
>wget https://github.com/rtorchia/DSC-AlarmServer/archive/refs/heads/main.zip
>
>unzip main.zip
>
>cd DSC-AlarmServer-main
### 2. Edit alarmserver.cfg
>apt update
>
>apt install nano
>
>nano alarmserver.cfg

### 3. Create docker image:
>docker build -t alarmserver .

### 4. Run/Create container:
>docker run -d -p 4025:4025 -p 8111:8111 -e TZ=America/Detroit --restart=always --name alarmserver

### To Edit alarmserver.cfg in container:
>docker exec -u 0 -it alarmserver /bin/bash
>
>apt update
>
>apt install nano
>
>nano alarmserver.cfg
>

#### Restart container
>docker restart alarmserver
