#!/usr/bin/python3
## Alarm Server
## Supporting Envisalink 2DS/3/4
## Written by donnyk+envisalink@gmail.com
## Lightly improved by leaberry@gmail.com
## Updated and modified for Python 3.8 by ralphtorchia1@gmail.com
## Smartthings away/stay mode by jordan@xeron.cc
## Converted from asyncore/asynchat to asyncio
##
## This code is under the terms of the GPL v3 license.
## ver: 2026-03-12
## This version removes SmartThings code that is no longer required as SmartThings no longer uses IDE/Groovy

import asyncio
import configparser
import datetime
import os, socket, sys, urllib.request, urllib.parse, urllib.error, ssl
import io, email
import json
import hashlib
import time
import getopt
import logging
import shutil
from logging.handlers import RotatingFileHandler

from envisalinkdefs import evl_ResponseTypes
from envisalinkdefs import evl_Defaults
from envisalinkdefs import evl_ArmModes
from envisalinkdefs import evl_ErrorCodes

LOGTOFILE = False

class CodeError(Exception): pass

ALARMSTATE={"version" : 0.1}
MAXPARTITIONS=16
MAXZONES=64
MAXALARMUSERS=95
EVENTCODES=[510,511,601,602,603,604,605,606,609,610,616,620,621,622,623,624,625,626,650,651,652,653,654,655,656,657,663,664,840,841]
CONNECTEDCLIENTS={}
TIMETOWAIT=2

def dict_merge(a, b):
    c = a.copy()
    c.update(b)
    return c

def getMessageType(code):
    return evl_ResponseTypes[code]

def alarmserver_logger(message, type=0, level=0):
    log_msg = str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")) + " " + message
    if LOGTOFILE:
        outfile.info(log_msg)
    else:
        print(log_msg)

def to_chars(string):
    chars = []
    for char in string:
        chars.append(ord(char))
    return chars

def get_checksum(code, data):
    strcheck = sum(to_chars(code) + to_chars(data))
    return format(strcheck, "02X")[-2:]


class AlarmServerConfig():
    def __init__(self, configfile):
        self._config = configparser.ConfigParser()
        self._config.read(configfile)

        self.LOGURLREQUESTS = self.read_config_var("alarmserver", "logurlrequests", True, "bool")
        self.LOGMAXSIZE = self.read_config_var("alarmserver", "logmaxsize", 102400, "int")
        self.LOGMAXBACKUPS = self.read_config_var("alarmserver", "logmaxbackups", 5, "int")
        self.HTTPPORT = self.read_config_var("alarmserver", "httpport", 8111, "int")
        self.CERTFILE = self.read_config_var("alarmserver", "certfile", "server.crt", "str")
        self.KEYFILE = self.read_config_var("alarmserver", "keyfile", "server.key", "str")
        self.MAXEVENTS = self.read_config_var("alarmserver", "maxevents", 10, "int")
        self.MAXALLEVENTS = self.read_config_var("alarmserver", "maxallevents", 100, "int")
        self.ENVISALINKHOST = self.read_config_var("envisalink", "host", "envisalink", "str")
        self.ENVISALINKPORT = self.read_config_var("envisalink", "port", 4025, "int")
        self.ENVISALINKPASS = self.read_config_var("envisalink", "pass", "user", "str")
        self.ENABLEPROXY = self.read_config_var("envisalink", "enableproxy", True, "bool")
        self.ENVISALINKPROXYPORT = self.read_config_var("envisalink", "proxyport", self.ENVISALINKPORT, "int")
        self.ENVISALINKPROXYPASS = self.read_config_var("envisalink", "proxypass", self.ENVISALINKPASS, "str")
        self.ALARMCODE = self.read_config_var("envisalink", "alarmcode", "1111", "str")
        self.EVENTTIMEAGO = self.read_config_var("alarmserver", "eventtimeago", True, "bool")
        self.LOGFILE = self.read_config_var("alarmserver", "logfile", "", "str")
        global LOGTOFILE
        if self.LOGFILE == "":
            LOGTOFILE = False
        else:
            LOGTOFILE = True

        self.PARTITIONNAMES = {}
        self.PARTITIONS = {}
        for i in range(1, MAXPARTITIONS + 1):
            self.PARTITIONNAMES[i] = self.read_config_var("partition" + str(i), "name", "", "str", True)

        self.ZONES = {}
        self.ZONENAMES = {}
        for i in range(1, MAXZONES + 1):
            self.ZONENAMES[i] = self.read_config_var("zone" + str(i), "name", "", "str", True)
            type = self.read_config_var("zone" + str(i), "type", "", "str", True)
            partition = self.read_config_var("zone" + str(i), "partition", "1", "str", True)

            if self.ZONENAMES[i] != "" and type != "":
                self.ZONES[i] = {}
                self.ZONES[i]["name"] = self.ZONENAMES[i]
                self.ZONES[i]["type"] = type
                self.ZONES[i]["partition"] = partition

        self.ALARMUSERNAMES = {}
        for i in range(1, MAXALARMUSERS + 1):
            self.ALARMUSERNAMES[i] = self.read_config_var("alarmserver", "user" + str(i), "", "str", True)

    def read_config_var(self, section, variable, default, type="str", quiet=False):
        try:
            if type == "str":
                return self._config.get(section, variable)
            elif type == "bool":
                return self._config.getboolean(section, variable)
            elif type == "int":
                return int(self._config.get(section, variable))
        except (configparser.NoSectionError, configparser.NoOptionError):
            self.defaulting(section, variable, default, quiet)
            return default

    def defaulting(self, section, variable, default, quiet=False):
        if quiet == False:
            print(("Config option " + str(variable) + " not set in [" + str(section) + "] defaulting to: \"" + str(default) + "\""))


class HTTPChannel:
    # Handles a single HTTP connection using asyncio streams

    def __init__(self, server, reader, writer):
        self.server = server
        self.reader = reader
        self.writer = writer

    async def handle(self):
        try:
            # Read until double CRLF (end of HTTP headers)
            raw = b""
            while b"\r\n\r\n" not in raw:
                chunk = await self.reader.read(4096)
                if not chunk:
                    break
                raw += chunk
                if len(raw) > 16384:
                    # limit header size to prevent attacks
                    return

            fp = io.StringIO(raw.decode("utf-8"))
            request_line = fp.readline().split()
            if len(request_line) != 3:
                return

            header = email.message_from_file(fp)
            method, path = request_line[0], request_line[1]
            self.server.handle_request(self, method, path, header)
        except Exception as e:
            alarmserver_logger("HTTP error: %s" % str(e))
        finally:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass

    def push(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.writer.write(data)

    def pushstatus(self, status, explanation="OK"):
        self.push("HTTP/1.0 %d %s\r\n" % (status, explanation))

    def pushok(self, content):
        self.pushstatus(200, "OK")
        self.push("Content-type: application/json\r\n")
        self.push("Expires: Sat, 26 Jul 1997 05:00:00 GMT\r\n")
        self.push("Last-Modified: " + datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S") + " GMT\r\n")
        self.push("Cache-Control: no-store, no-cache, must-revalidate\r\n")
        self.push("Cache-Control: post-check=0, pre-check=0\r\n")
        self.push("Pragma: no-cache\r\n")
        self.push(b"\r\n")
        self.push(content)

    def pushfile(self, file):
        self.pushstatus(200, "OK")
        extension = os.path.splitext(file)[1]
        if extension == ".html":
            self.push(b"Content-type: text/html\r\n")
        elif extension == ".js":
            self.push(b"Content-type: text/javascript\r\n")
        elif extension == ".png":
            self.push(b"Content-type: image/png\r\n")
        elif extension == ".css":
            self.push(b"Content-type: text/css\r\n")
        self.push(b"\r\n")
        filepath = sys.path[0] + os.sep + "ext" + os.sep + file
        with open(filepath, "rb") as f:
            while True:
                data = f.read(2048)
                if not data:
                    break
                self.writer.write(data)


class EnvisalinkClient(asyncio.Protocol):
    # Asyncio protocol for the Envisalink TCP connection

    def __init__(self, config):
        self._config = config
        self._buffer = b""
        self._loggedin = False
        self._retrydelay = 10
        self._transport = None
        self._loop = None

    def connection_made(self, transport):
        self._transport = transport
        alarmserver_logger("Connected to %s:%i" % (self._config.ENVISALINKHOST, self._config.ENVISALINKPORT))

    def data_received(self, data):
        self._buffer += data
        while b"\r\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\r\n", 1)
            self.handle_line(line.decode("utf-8"))

    def connection_lost(self, exc):
        self._loggedin = False
        alarmserver_logger("Disconnected from %s:%i" % (self._config.ENVISALINKHOST, self._config.ENVISALINKPORT))
        if self._loop:
            self._loop.call_later(self._retrydelay, self._schedule_reconnect)

    def _schedule_reconnect(self):
        alarmserver_logger("Retrying connection in %d seconds..." % self._retrydelay)
        asyncio.ensure_future(self._reconnect(), loop=self._loop)

    async def _reconnect(self):
        alarmserver_logger("Reconnecting to %s:%i" % (self._config.ENVISALINKHOST, self._config.ENVISALINKPORT))
        try:
            transport, _ = await self._loop.create_connection(
                lambda: self,
                self._config.ENVISALINKHOST,
                self._config.ENVISALINKPORT
            )
            self._transport = transport
        except Exception as e:
            alarmserver_logger("Reconnect failed: %s" % str(e))
            self._loop.call_later(self._retrydelay, self._schedule_reconnect)

    def error_received(self, exc):
        self._loggedin = False
        alarmserver_logger("Error on Envisalink connection: %s" % str(exc))

    def send_command(self, code, data="", checksum=True):
        if checksum:
            to_send = code + data + get_checksum(code, data) + "\r\n"
        else:
            to_send = code + data + "\r\n"
        alarmserver_logger("TX > " + to_send[:-2])
        if self._transport:
            self._transport.write(to_send.encode("utf-8"))

    def handle_line(self, input):
        if input != "":
            for client in CONNECTEDCLIENTS:
                CONNECTEDCLIENTS[client].send_command(input, checksum=False)

            try:
                code = int(input[:3])
                parameters = input[3:][:-2]
                event = getMessageType(code)
                message = self.format_event(event, parameters)
                alarmserver_logger("RX < " + str(code) + " - " + parameters + " - " + message)
                if code == 502:
                    errcode = int(input[3:6])
                    alarmserver_logger(" => " + message + " = " + evl_ErrorCodes[errcode])

                try:
                    handler = "handle_%s" % evl_ResponseTypes[code]["handler"]
                except KeyError:
                    self.handle_event(code, parameters, event, message)
                    return

                try:
                    func = getattr(self, handler)
                except AttributeError:
                    raise CodeError("Handler function doesn't exist")

                func(code, parameters, event, message)

            except Exception:
                alarmserver_logger("Unsupported input! This could be a bug. Input was: " + str(input))

    def format_event(self, event, parameters):
        if "type" in event:
            if event["type"] in ("partition", "zone"):
                if event["type"] == "partition":
                    if int(parameters[0]) in self._config.PARTITIONNAMES and self._config.PARTITIONNAMES[int(parameters[0])] != "":
                        if len(str(parameters)) == 5:
                            try:
                                usercode = int(parameters[1:5])
                            except:
                                usercode = 0

                            if int(usercode) in self._config.ALARMUSERNAMES:
                                if self._config.ALARMUSERNAMES[int(usercode)] != False:
                                    alarmusername = self._config.ALARMUSERNAMES[int(usercode)]
                                else:
                                    alarmusername = usercode
                                return event["name"].format(str(self._config.PARTITIONNAMES[int(parameters[0])]), str(alarmusername))

                        elif len(parameters) == 2:
                            armmode = evl_ArmModes[int(parameters[1])]
                            return event["name"].format(str(self._config.PARTITIONNAMES[int(parameters[0])]), str(armmode))
                        elif len(parameters) == 1:
                            return event["name"].format(str(self._config.PARTITIONNAMES[int(parameters)]))
                        else:
                            return event["name"].format(str(self._config.PARTITIONNAMES[int(parameters[0])]), int(parameters[1:]))

                elif event["type"] == "zone":
                    if int(parameters) in self._config.ZONENAMES and self._config.ZONENAMES[int(parameters)] != "":
                        return event["name"].format(str(self._config.ZONENAMES[int(parameters)]))

        return event["name"].format(str(parameters))

    # envisalink event handlers, some events are unhandeled.
    def handle_login(self, code, parameters, event, message):
        if parameters == "3":
            self._loggedin = True
            self.send_command("005", self._config.ENVISALINKPASS)
        if parameters == "1":
            self.send_command("001", "")
            # this was to update bypass status, but sometimes would change alarm arm status from stay/away
            # time.sleep(2)
            # self.send_command("071", "1*1#")
        if parameters == "0":
            alarmserver_logger("Incorrect envisalink password")
            sys.exit(0)

    def handle_event(self, code, parameters, event, message):
        if "type" in event:
            if not event["type"] in ALARMSTATE:
                ALARMSTATE[event["type"]] = {"lastevents": []}

            if event["type"] in ("partition", "zone"):
                if event["type"] == "zone":
                    if int(parameters) in self._config.ZONENAMES:
                        if self._config.ZONENAMES[int(parameters)] != "":
                            if not int(parameters) in ALARMSTATE[event["type"]]:
                                ALARMSTATE[event["type"]][int(parameters)] = {"name": self._config.ZONENAMES[int(parameters)]}
                        else:
                            if not int(parameters) in ALARMSTATE[event["type"]]:
                                ALARMSTATE[event["type"]][int(parameters)] = {}

                elif event["type"] == "partition":
                    if int(parameters[0]) in self._config.PARTITIONNAMES:
                        if self._config.PARTITIONNAMES[int(parameters[0])] != "":
                            if not int(parameters) in ALARMSTATE[event["type"]]:
                                ALARMSTATE[event["type"]][int(parameters)] = {"name": self._config.PARTITIONNAMES[int(parameters)]}
                        else:
                            if not int(parameters) in ALARMSTATE[event["type"]]:
                                ALARMSTATE[event["type"]][int(parameters)] = {}
            else:
                if not int(parameters) in ALARMSTATE[event["type"]]:
                    ALARMSTATE[event["type"]][int(parameters)] = {}

            if "lastevents" not in ALARMSTATE[event["type"]][int(parameters)]:
                ALARMSTATE[event["type"]][int(parameters)]["lastevents"] = []
            if "status" not in ALARMSTATE[event["type"]][int(parameters)]:
                if "type" not in event:
                    ALARMSTATE[event["type"]][int(parameters)]["status"] = {}
                else:
                    ALARMSTATE[event["type"]][int(parameters)]["status"] = evl_Defaults[event["type"]]

            if "status" in event:
                ALARMSTATE[event["type"]][int(parameters)]["status"] = dict_merge(
                    ALARMSTATE[event["type"]][int(parameters)]["status"], event["status"]
                )

            if len(ALARMSTATE[event["type"]][int(parameters)]["lastevents"]) > self._config.MAXEVENTS:
                ALARMSTATE[event["type"]][int(parameters)]["lastevents"].pop(0)

            ALARMSTATE[event["type"]][int(parameters)]["lastevents"].append(
                {"datetime": str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")), "message": message}
            )

            if len(ALARMSTATE[event["type"]]["lastevents"]) > self._config.MAXALLEVENTS:
                ALARMSTATE[event["type"]]["lastevents"].pop(0)

            ALARMSTATE[event["type"]]["lastevents"].append(
                {"datetime": str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")), "message": message}
            )

    def handle_zone(self, code, parameters, event, message):
        self.handle_event(code, parameters[1:], event, message)

    def handle_partition(self, code, parameters, event, message):
        self.handle_event(code, parameters[0], event, message)


class ProxyChannel(asyncio.Protocol):
    # Handles a single proxy client connection

    def __init__(self, server, proxypass, addr):
        self.server = server
        self._proxypass = proxypass
        self._straddr = str(addr)
        self._clientMD5 = hashlib.md5(str(addr).encode("ASCII")).hexdigest()
        self._authenticated = False
        self._buffer = b""
        self._transport = None

    def connection_made(self, transport):
        self._transport = transport
        self.send_command("5053")

    def data_received(self, data):
        self._buffer += data
        while b"\r\n" in self._buffer:
            line_bytes, self._buffer = self._buffer.split(b"\r\n", 1)
            self.handle_line(line_bytes.decode("utf-8"))

    def connection_lost(self, exc):
        alarmserver_logger("Proxy connection from %s closed" % self._straddr)
        if self._straddr in CONNECTEDCLIENTS:
            del CONNECTEDCLIENTS[self._straddr]

    def handle_line(self, line):
        alarmserver_logger("PROXY REQ < " + line)
        if self._authenticated:
            self.server._envisalinkclient.send_command(line, "", False)
        else:
            self.send_command("500005")
            expectedstring = "005" + self._proxypass + get_checksum("005", self._proxypass)
            if line == expectedstring:
                alarmserver_logger("Proxy User Authenticated")
                CONNECTEDCLIENTS[self._straddr] = self
                self._authenticated = True
                self.send_command("5051")
            else:
                alarmserver_logger("Proxy User Authentication failed")
                self.send_command("5050")
                if self._transport:
                    self._transport.close()

    def send_command(self, data, checksum=True):
        if checksum:
            to_send = data + get_checksum(data, "") + "\r\n"
        else:
            to_send = data + "\r\n"
        if self._transport:
            self._transport.write(to_send.encode("utf-8"))


class AlarmServer:
    # Main alarm server: manages the HTTP server, Envisalink client, and proxy

    def __init__(self, config):
        self._config = config
        self._envisalinkclient = None
        self._loop = None

    def handle_request(self, channel, method, request, header):
        if self._config.LOGURLREQUESTS:
            alarmserver_logger("Web request: " + str(method) + " " + str(request))

        query = urllib.parse.urlparse(request)
        query_array = urllib.parse.parse_qs(query.query, True)

        if "alarmcode" in query_array:
            alarmcode = str(query_array["alarmcode"][0])
        else:
            alarmcode = str(self._config.ALARMCODE)

        if "part" in query_array:
            part = str(query_array["part"][0])
        else:
            part = "1"

        if query.path == "/":
            channel.pushfile("index.html")
        elif query.path in ("/2", "/3"):
            redirect_url = "http://{}{}".format(self._config.ENVISALINKHOST, query.path)
            #redirect_url = "http://{}:{}{}".format(self._config.ENVISALINKHOST, self._config.ENVISALINKPORT, query.path)
            channel.pushstatus(302, "Found")
            channel.push("Location: {}\r\n".format(redirect_url))
            channel.push("\r\n")
        elif query.path == "/api":
            channel.pushok(json.dumps(ALARMSTATE))
        elif query.path == "/api/alarm/arm":
            channel.pushok(json.dumps({"response": "Request to arm received"}))
            self._envisalinkclient.send_command("030", part)
        elif query.path == "/api/alarm/stayarm":
            channel.pushok(json.dumps({"response": "Request to arm in stay received"}))
            self._envisalinkclient.send_command("031", part)
        elif query.path == "/api/alarm/toggleinstant":
            channel.pushok(json.dumps({"response": "Request to toggle instant mode received"}))
            self._envisalinkclient.send_command("032", part)
        elif query.path == "/api/alarm/instantarm":
            channel.pushok(json.dumps({"response": "Request to arm in instant mode received"}))
            self._envisalinkclient.send_command("071", part + "*9" + alarmcode + "#")
        elif query.path == "/api/alarm/togglenight":
            channel.pushok(json.dumps({"response": "Request to toggle night mode received"}))
            self._envisalinkclient.send_command("071", part + "**#")
        elif query.path == "/api/alarm/togglechime":
            channel.pushok(json.dumps({"response": "Request to toggle chime mode received"}))
            self._envisalinkclient.send_command("071", part + "*4#")
        elif query.path == "/api/alarm/armwithcode":
            channel.pushok(json.dumps({"response": "Request to arm with code received"}))
            self._envisalinkclient.send_command("033", part + alarmcode)
        elif query.path == "/api/alarm/bypass":
            try:
                zones = str(query_array["zone"][0]).split(",")
                for zone in zones:
                    if str(zone) == "0":
                        partition = part
                    else:
                        partition = str(self._config.ZONES[int(zone)]["partition"])

                    if len(zone) == 1:
                        zone = "0" + zone

                    alarmserver_logger("request to bypass zone %s on partition %s" % (zone, partition))
                    channel.pushok(json.dumps({"response": "Request to bypass zone received"}))
                    self._envisalinkclient.send_command("071", partition + "*1" + str(zone) + "#")
                    time.sleep(2)
            except Exception:
                channel.pushok(json.dumps({"response": "Request to bypass zone received but invalid zone given!"}))
        elif query.path == "/api/alarm/panic":
            try:
                type = str(query_array["type"][0])
                alarmserver_logger("request to panic type %s" % type)
                channel.pushok(json.dumps({"response": "Request to panic received"}))
                self._envisalinkclient.send_command("060", str(type))
            except Exception:
                channel.pushok(json.dumps({"response": "Request to panic received but invalid type given!"}))
        elif query.path == "/api/alarm/reset":
            channel.pushok(json.dumps({"response": "Request to reset sensors received"}))
            self._envisalinkclient.send_command("071", part + "*72#")
        elif query.path == "/api/alarm/refresh":
            channel.pushok(json.dumps({"response": "Request to refresh received"}))
            self._envisalinkclient.send_command("001", "")
            time.sleep(2)
            self._envisalinkclient.send_command("071", part + "*1#")
        elif query.path == "/api/pgm":
            channel.pushok(json.dumps({"response": "Request to trigger PGM"}))
            self._envisalinkclient.send_command("071", part + "*7" + str(query_array["pgmnum"][0]) + "#")
        elif query.path == "/api/alarm/disarm":
            channel.pushok(json.dumps({"response": "Request to disarm received"}))
            self._envisalinkclient.send_command("040", part + alarmcode)
        elif query.path == "/api/config/eventtimeago":
            channel.pushok(json.dumps({"eventtimeago": str(self._config.EVENTTIMEAGO)}))
        elif query.path == "/api/setclock":
            # clock format hhmmMMDDYY
            # Note: it may take up to 4 minutes for this command to be reflected on all the keypads on the security system
            channel.pushok(json.dumps({"response": "Request to set clock"}))
            self._envisalinkclient.send_command("010", part)
        elif query.path == "/img/glyphicons-halflings.png":
            channel.pushfile("glyphicons-halflings.png")
        elif query.path == "/img/glyphicons-halflings-white.png":
            channel.pushfile("glyphicons-halflings-white.png")
        elif query.path == "/favicon.ico":
            channel.pushfile("favicon.ico")
        elif query.path == "/logfile":
            if LOGTOFILE:
                try:
                    src_path = r"" + self._config.LOGFILE
                    dest_path = r"ext" + os.sep + "output.log"
                    shutil.copy(src_path, dest_path)
                    channel.pushfile("output.log")
                except Exception:
                    alarmserver_logger("No logfile found at: " + self._config.LOGFILE)
        else:
            if len(query.path.split("/")) == 2:
                try:
                    with open(sys.path[0] + os.sep + "ext" + os.sep + query.path.split("/")[1]) as f:
                        f.close()
                        channel.pushfile(query.path.split("/")[1])
                except IOError as e:
                    print("I/O error({0}): {1}".format(e.errno, e.strerror))
                    channel.pushstatus(404, "Not found")
                    channel.push("Content-type: text/html\r\n")
                    channel.push("File not found\r\n")
            else:
                if self._config.LOGURLREQUESTS:
                    alarmserver_logger("Invalid file requested")
                channel.pushstatus(404, "Not found")
                channel.push("Content-type: text/html\r\n")
                channel.push("\r\n")

async def run_server(config):
    global outfile

    alarmserver_logger("====================================")
    alarmserver_logger("Alarm Server Starting...")
    alarmserver_logger("Currently Supporting Envisalink 2DS/3/4 only")
    alarmserver_logger("Tested on a DSC PC1616 + EVL-3")
    alarmserver_logger("and on a DSC PC1832 + EVL-2DS")
    alarmserver_logger("and on a DSC PC1832 v4.6 + EVL-4")
    alarmserver_logger("and on a DSC PC1864 v4.6 + EVL-3")
    alarmserver_logger("and on a DSC PC1864 v4.6 + EVL-4")
    alarmserver_logger("====================================")

    loop = asyncio.get_event_loop()
    server = AlarmServer(config)

    # Connect to Envisalink
    envisalink_client = EnvisalinkClient(config)
    envisalink_client._loop = loop
    try:
        transport, _ = await loop.create_connection(
            lambda: envisalink_client,
            config.ENVISALINKHOST,
            config.ENVISALINKPORT
        )
    except Exception as e:
        alarmserver_logger("Error connecting to Envisalink: %s" % str(e))
        raise

    server._envisalinkclient = envisalink_client

    # Start HTTP server
    async def http_handler(reader, writer):
        addr = writer.get_extra_info("peername")
        if config.LOGURLREQUESTS:
            alarmserver_logger("Incoming web connection from %s" % repr(addr))
        channel = HTTPChannel(server, reader, writer)
        await channel.handle()

    http_server = await asyncio.start_server(http_handler, "", config.HTTPPORT)
    alarmserver_logger("HTTP server listening on port %d" % config.HTTPPORT)

    # Start proxy server if enabled
    proxy_server = None
    if config.ENABLEPROXY:
        async def proxy_handler(reader, writer):
            addr = writer.get_extra_info("peername")
            alarmserver_logger("Incoming proxy connection from %s" % repr(addr))
            proxy_ch = ProxyChannel(server, config.ENVISALINKPROXYPASS, addr)
            # Wire up transport manually via a bridge
            bridge = _AsyncioBridge(proxy_ch, reader, writer)
            await bridge.run()

        proxy_server = await asyncio.start_server(proxy_handler, "", config.ENVISALINKPROXYPORT)
        alarmserver_logger("Envisalink Proxy Started on port %d" % config.ENVISALINKPROXYPORT)

    try:
        async with http_server:
            if proxy_server:
                async with proxy_server:
                    await asyncio.gather(
                        http_server.serve_forever(),
                        proxy_server.serve_forever()
                    )
            else:
                await http_server.serve_forever()
    except asyncio.CancelledError:
        alarmserver_logger("Server shutting down.")


class _AsyncioBridge:
    # Bridges asyncio streams to the ProxyChannel Protocol-style object

    def __init__(self, protocol, reader, writer):
        self._protocol = protocol
        self._reader = reader
        self._writer = writer
        # Provide a minimal transport shim
        self._protocol._transport = _WriterTransport(writer)
        self._protocol.connection_made(self._protocol._transport)

    async def run(self):
        try:
            while True:
                data = await self._reader.read(4096)
                if not data:
                    break
                self._protocol.data_received(data)
        except Exception as e:
            alarmserver_logger("Proxy bridge error: %s" % str(e))
        finally:
            self._protocol.connection_lost(None)
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass


class _WriterTransport:
    # Minimal asyncio Transport shim backed by a StreamWriter

    def __init__(self, writer):
        self._writer = writer

    def write(self, data):
        self._writer.write(data)

    def close(self):
        self._writer.close()


def mainSetup(conffile):
    global config, outfile

    if not os.path.exists(conffile):
        print("Could not find configuration file %s" % conffile)
        sys.exit()

    config = AlarmServerConfig(conffile)
    print("Using configuration file %s" % conffile)

    if LOGTOFILE:
        outfile_handler = RotatingFileHandler(
            config.LOGFILE, mode="a",
            maxBytes=config.LOGMAXSIZE,
            backupCount=config.LOGMAXBACKUPS
        )
        outfile = logging.getLogger()
        outfile.setLevel(logging.INFO)
        outfile.addHandler(outfile_handler)
        print("Writing logfile to %s" % config.LOGFILE)

    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        alarmserver_logger("Server interrupted by Ctrl+C.")


def main(argv):
    try:
        opts, args = getopt.getopt(argv, "hc:", ["help", "config="])
    except getopt.GetoptError:
        usage()
        sys.exit(2)

    for opt, arg in opts:
        if opt in ("-h", "--help"):
            usage()
            sys.exit()
        elif opt in ("-c", "--config"):
            mainSetup(arg)


def usage():
    print("Usage: " + sys.argv[0] + " -c <file>")


if __name__ == "__main__":
    main(sys.argv[1:])

    cfg_file = "alarmserver.cfg"
    pathname = os.path.dirname(sys.argv[0])
    scriptpath = os.path.abspath(pathname)
    conffile = os.path.join(scriptpath, cfg_file)
    mainSetup(conffile)
