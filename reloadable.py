self_client_ident = "You!anon@localhost"
anon_client_ident = "Anonymous!anon@localhost"

# Rewrite "you"s in messages to minimise needless highlights.
import re

cyrillic_small_o = "о"
cyrillic_capital_o = "О"

exchange_regex = re.compile("you", re.I)
privmsg_regex = re.compile("PRIVMSG\s(?P<channel>.+?)\s:?(?P<msg>.+)")


def exchange(string: str) -> str:
    for match in exchange_regex.finditer(string):
        location = match.start() + 1

        if string[location] == "o":
            char = cyrillic_small_o
        else:
            char = cyrillic_capital_o

        string = string[:location] + char + string[location + 1 :]
    return string


class Client:
    def __init__(self, client):
        self.client = client

    def write(self, string: str, log=True):
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
        self.write(f":thewired 376 :Stay comfy")

    def send_notice(self, channel: str, msg: str):
        self.write(f":admin NOTICE {channel} :{msg}")

    def send_privmsg(self, channel: str, msg: str):
        self.write(f":{anon_client_ident} PRIVMSG {channel} :{msg}")

    def send_join(self, channel: str):
        self.client.channels.add(channel)
        self.write(f":{anon_client_ident} TOPIC {channel} :{channel}")
        self.write(f":{self_client_ident} JOIN :{channel}")
        self.write(f":thewired 353 You = {channel} :You Anonymous")

    def send_part(self, channel: str):
        self.write(f":{self_client_ident} PART :{channel}")


def process_message(data, client, clients):
    client = Client(client)

    message = data.decode().strip()
    print(message)
    message_parts = message.split(" ")
    if message.startswith("PING"):
        if len(message_parts) > 1:
            token = message_parts[1]
            client.send_pong(token)
    elif message.startswith("USER"):
        client.send_welcome()
        client.send_join("#random")
    elif message.startswith("WHOIS"):
        client.send_whois()
    elif message.startswith("JOIN"):
        if len(message_parts) > 1:
            channel = message_parts[1]
            client.send_join(channel)
            clients_num = len([c for c in clients if channel in c.channels])
            client.send_notice(
                channel,
                f"welcome to {channel}, there might be about {clients_num} people connected right now",
            )
    elif message.startswith("PART"):
        if len(message_parts) > 1:
            channel = message_parts[1]
            client.channels.remove(channel)
            client.send_part(channel)
    elif message.startswith("PRIVMSG"):
        if len(message_parts) >= 2:
            match = privmsg_regex.search(message)

            if match:
                channel = match.group("channel")
                msg = match.group("msg")
                msg = exchange(msg)
                for c in clients:
                    if channel in c.channels and c != client:
                        Client(c).send_privmsg(channel, msg)
