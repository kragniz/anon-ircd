import re
import subprocess
import prometheus_client

self_client_ident = "You!anon@localhost"
anon_client_ident = "Anonymous!anon@localhost"

# Rewrite "you"s in messages to minimise needless highlights.

cyrillic_small_o = "о"
cyrillic_capital_o = "О"

exchange_regex = re.compile("you", re.I)
privmsg_regex = re.compile("PRIVMSG\s(?P<channel>.+?)\s:?(?P<msg>.+)")
notice_regex = re.compile("NOTICE\s(?P<channel>.+?)\s:?(?P<msg>.+)")


def exchange(string: str) -> str:
    for match in exchange_regex.finditer(string):
        location = match.start() + 1

        if string[location] == "o":
            char = cyrillic_small_o
        else:
            char = cyrillic_capital_o

        string = string[:location] + char + string[location + 1 :]
    return string


def make_reloadable_collector(collector_cls, name, description, labelnames=None):
    if labelnames is None:
        labelnames = []
    collector = collector_cls(name, description, labelnames, registry=None)

    try:
        for name in prometheus_client.REGISTRY._get_names(collector):
            found_collector = prometheus_client.REGISTRY._names_to_collectors.pop(name)
        prometheus_client.REGISTRY._collector_to_names.pop(found_collector)
    except KeyError:
        print(f"couldn't unregister {name}, is it a new collector?")
    prometheus_client.REGISTRY.register(collector)
    return collector


MSG_SEND_TIME = make_reloadable_collector(
    prometheus_client.Summary, "msg_send_seconds", "Time spent sending each messge",
)


class Client:
    def __init__(self, client):
        self.client = client

    @property
    def channels(self):
        return self.client.channels

    @MSG_SEND_TIME.time()
    def write(self, string: str, log=False):
        if log:
            print(f"-> {string}")
        self.client.writer.write(f"{string}\r\n".encode())

    def send_ping(self):
        self.write(f"PING :001", log=False)

    def send_pong(self, token):
        self.write(f"PONG {token}", log=False)

    def send_whois(self):
        self.write(
            f":thewired 311 navi Anonymous Anonymous anon@localhost * :Anonymous"
        )

    def send_welcome(self):
        self.write(f":thewired 001 You :Welcome to The Wired")
        self.write(f":thewired 376 :")
        self.write(f":thewired 376 :Rules:")
        self.write(f":thewired 376 :  0. Stay comfy")
        self.write(f":thewired 376 :")
        self.write(
            f":thewired 376 :Join #random for discussion, #dev for development chat"
        )

    def send_admin_notice(self, channel: str, msg: str):
        self.write(f":Admin NOTICE {channel} :{msg}")

    def send_privmsg(self, channel: str, msg: str):
        self.write(f":{anon_client_ident} PRIVMSG {channel} :{msg}")

    def send_notice(self, channel: str, msg: str):
        self.write(f":{anon_client_ident} NOTICE {channel} :{msg}")

    def send_join(self, channel: str):
        self.client.channels.add(channel)
        self.write(f":{anon_client_ident} TOPIC {channel} :{channel}")
        self.write(f":{self_client_ident} JOIN :{channel}")
        self.write(f":thewired 353 You = {channel} :You Anonymous")

    def send_part(self, channel: str):
        self.write(f":{self_client_ident} PART :{channel}")

    def send_server_notice(self, msg: str):
        self.write(f":Admin NOTICE : {msg}")


MESSAGE_TIME = make_reloadable_collector(
    prometheus_client.Summary,
    "message_processing_seconds",
    "Time spent processing message",
)

CLIENTS_CONNECTED = make_reloadable_collector(
    prometheus_client.Gauge,
    "clients_connected",
    "Number of clients currently connected",
)

CHANNEL_MEMBERS = make_reloadable_collector(
    prometheus_client.Gauge,
    "channel_members",
    "Number of members of each channel",
    ["channel"],
)

TOTAL_MSGS = make_reloadable_collector(
    prometheus_client.Counter, "messages_total", "Number of messages sent", ["channel"],
)

TOTAL_REQUESTS = make_reloadable_collector(
    prometheus_client.Counter, "requests_total", "Number of requests sent", ["type"],
)

TOTAL_REQUEST_ERRORS = make_reloadable_collector(
    prometheus_client.Counter,
    "request_error_total",
    "Number of errors in processing requests",
)


def count_channel_members(channel, clients):
    return len([c for c in clients if channel in c.channels])


@MESSAGE_TIME.time()
@TOTAL_REQUEST_ERRORS.count_exceptions()
def process_message(data, client, clients):
    client = Client(client)

    message = data.decode().strip()
    message_parts = message.split(" ")

    request_type = message_parts[0]

    if request_type == "PING":
        request_type = "PING"
        if len(message_parts) > 1:
            token = message_parts[1]
            client.send_pong(token)

    elif request_type == "USER":
        client.send_welcome()
        default_channels = {"#random", "#dev"}
        for channel in default_channels:
            client.send_join(channel)
            clients_num = count_channel_members(channel, clients)
            CHANNEL_MEMBERS.labels(channel=channel).set(clients_num)

    elif request_type == "WHOIS":
        client.send_whois()

    elif request_type == "JOIN":
        if len(message_parts) > 1:
            channel = message_parts[1]
            if len(client.channels) > 25:
                client.send_server_notice("Too many channels joined")
            else:
                client.send_join(channel)
                clients_num = count_channel_members(channel, clients)
                CHANNEL_MEMBERS.labels(channel=channel).set(clients_num)
                client.send_admin_notice(
                    channel,
                    f"welcome to {channel}, there might be about {clients_num} people connected right now",
                )

    elif request_type == "PART":
        if len(message_parts) > 1:
            channel = message_parts[1]
            client.channels.remove(channel)
            client.send_part(channel)
            clients_num = count_channel_members(channel, clients)
            CHANNEL_MEMBERS.labels(channel=channel).set(clients_num)

    elif request_type == "PRIVMSG":
        if len(message_parts) >= 2:
            match = privmsg_regex.search(message)

            if match:
                channel = match.group("channel")
                TOTAL_MSGS.labels(channel=channel).inc()
                msg = match.group("msg")
                msg = exchange(msg)
                for c in clients:
                    if channel in c.channels and c != client.client:
                        Client(c).send_privmsg(channel, msg)

    elif request_type == "NOTICE":
        if len(message_parts) >= 2:
            match = notice_regex.search(message)

            if match:
                channel = match.group("channel")
                TOTAL_MSGS.labels(channel=channel).inc()
                msg = match.group("msg")
                msg = exchange(msg)
                for c in clients:
                    if channel in c.channels and c != client.client:
                        Client(c).send_notice(channel, msg)

    else:
        print(f"UNKNOWN request: {message}")
        request_type = "UNKNOWN"

    TOTAL_REQUESTS.labels(type=request_type).inc()


def on_client_connect(client, clients):
    addr = client.writer.get_extra_info("peername")
    print(f"{addr!r} connected")
    CLIENTS_CONNECTED.inc()


def on_client_disconnect(client, clients):
    addr = client.writer.get_extra_info("peername")
    print(f"{addr!r} disconnected")
    CLIENTS_CONNECTED.dec()
    for channel in client.channels:
        clients_num = count_channel_members(channel, clients)
        CHANNEL_MEMBERS.labels(channel=channel).set(clients_num)


VERSION = make_reloadable_collector(
    prometheus_client.Info, "version", "Current version",
)


def reload(clients, current_version=None):
    CLIENTS_CONNECTED.set(len(clients))
    version = (
        subprocess.check_output(["git", "describe", "--tags", "--always", "--dirty="])
        .decode("utf-8")
        .strip()
    )

    VERSION.info({"version": version})

    checked_channels = set()
    for client in clients:
        for channel in client.channels:
            if not channel in checked_channels:
                clients_num = count_channel_members(channel, clients)
                CHANNEL_MEMBERS.labels(channel=channel).set(clients_num)
                checked_channels.add(channel)

    if current_version is not None:
        log = (
            subprocess.check_output(
                [
                    "git",
                    "log",
                    "--date=relative",
                    '--pretty=format:"%h %s (by %an, %ad)"',
                    f"{current_version}..{version}",
                ]
            )
            .decode("utf-8")
            .strip()
            .split("\n")
        )

        log = [f"Server reloaded with changes:"] + [
            "  " + s.strip('"') for s in filter(None, log)
        ]
        for line in log:
            for c in clients:
                if "#dev" in c.channels:
                    Client(c).send_admin_notice("#dev", line)

    return version
