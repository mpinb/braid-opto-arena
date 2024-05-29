# flydra_proxy.py
import requests
import json
import socket


class Flydra2Proxy:
    """
    A class that provides a proxy interface to interact with Flydra2.

    Args:
        flydra2_url (str): The URL of the Flydra2 server.

    Attributes:
        flydra2_url (str): The URL of the Flydra2 server.
        session (requests.Session): The session object for making HTTP requests.

    Raises:
        AssertionError: If the initial request to the Flydra2 server fails.

    """

    def __init__(self, flydra2_url: str = "http://10.40.80.6:8397/"):
        self.flydra2_url = flydra2_url
        self.session = requests.session()
        r = self.session.get(self.flydra2_url)
        assert r.status_code == requests.codes.ok

    def data_stream(self):
        """
        Generator function that yields data from the Flydra2 server.

        Yields:
            dict: A dictionary containing the parsed data from the server.

        """
        events_url = self.flydra2_url + "events"
        r = self.session.get(
            events_url, stream=True, headers={"Accept": "text/event-stream"}
        )
        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            data = self.parse_chunk(chunk)
            if data:
                yield data

    def parse_chunk(self, chunk):
        """
        Parses a chunk of data received from the Flydra2 server.

        Args:
            chunk (str): The chunk of data to parse.

        Returns:
            dict: A dictionary containing the parsed data.

        Raises:
            AssertionError: If the chunk does not have the expected format.

        """
        DATA_PREFIX = "data: "
        lines = chunk.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "event: braid"
        assert lines[1].startswith(DATA_PREFIX)
        buf = lines[1][len(DATA_PREFIX) :]
        data = json.loads(buf)
        return data

    def send_to_udp(self, udp_host, udp_port):
        """
        Sends data from the Flydra2 server to a UDP socket.

        Args:
            udp_host (str): The IP address or hostname of the UDP server.
            udp_port (int): The port number of the UDP server.

        """
        addr = (udp_host, udp_port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for data in self.data_stream():
            version = data.get("v", 1)
            assert version == 2
            try:
                update_dict = data["msg"]["Update"]
            except KeyError:
                continue
            msg = "%s, %s, %s" % (update_dict["x"], update_dict["y"], update_dict["z"])
            msg = msg.encode("ascii")
            sock.sendto(msg, addr)
