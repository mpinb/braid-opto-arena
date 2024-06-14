import requests
import json
import socket
import logging
from typing import Generator, Dict
from log_config import setup_logging

setup_logging(level="INFO")
logger = logging.getLogger(__name__)


class Flydra2Proxy:
    """
    A class that provides a proxy interface to interact with Flydra2.

    Args:
        flydra2_url (str): The URL of the Flydra2 server.

    Attributes:
        flydra2_url (str): The URL of the Flydra2 server.
        session (requests.Session): The session object for making HTTP requests.
    """

    def __init__(self, flydra2_url: str = "http://10.40.80.6:8397/"):
        self.flydra2_url = flydra2_url
        self.session = requests.Session()
        try:
            r = self.session.get(self.flydra2_url)
            r.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to connect to Flydra2 server: {e}")
            raise

    def data_stream(self) -> Generator[Dict, None, None]:
        """
        Generator function that yields data from the Flydra2 server.

        Yields:
            dict: A dictionary containing the parsed data from the server.
        """
        events_url = self.flydra2_url + "events"
        try:
            r = self.session.get(
                events_url, stream=True, headers={"Accept": "text/event-stream"}
            )
            r.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to get events stream from Flydra2 server: {e}")
            return

        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            data = self.parse_chunk(chunk)
            if data:
                yield data

    def parse_chunk(self, chunk: str) -> Dict:
        """
        Parses a chunk of data received from the Flydra2 server.

        Args:
            chunk (str): The chunk of data to parse.

        Returns:
            dict: A dictionary containing the parsed data.
        """
        DATA_PREFIX = "data: "
        lines = chunk.strip().split("\n")
        if (
            len(lines) != 2
            or lines[0] != "event: braid"
            or not lines[1].startswith(DATA_PREFIX)
        ):
            logger.warning(f"Unexpected chunk format: {chunk}")
            return {}

        buf = lines[1][len(DATA_PREFIX) :]
        try:
            data = json.loads(buf)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON data: {e}")
            return {}

        return data

    def send_to_udp(self, udp_host: str, udp_port: int):
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
            if version != 2:
                logger.warning(f"Unexpected version: {version}")
                continue

            try:
                update_dict = data["msg"]["Update"]
            except KeyError:
                logger.warning("Missing 'Update' key in data message")
                continue

            msg = f"{update_dict['x']}, {update_dict['y']}, {update_dict['z']}"
            sock.sendto(msg.encode("ascii"), addr)


if __name__ == "__main__":
    import time

    braidz_proxy = Flydra2Proxy()

    for data in braidz_proxy.data_stream():
        print(data)
        time.sleep(1)
