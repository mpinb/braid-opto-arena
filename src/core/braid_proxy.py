import requests
import json
from typing import Dict, Any, Optional
from src.utils.log_config import setup_logging
from src.core.messages import Publisher

logger = setup_logging(logger_name="BraidProxy", level="INFO")


class BraidProxy:
    """
    Proxy class for Braid server.
    """

    def __init__(
        self,
        braid_url: str = "http://10.40.80.6:8397/",
        port: int = 12345,
    ):
        """
        Initialize BraidProxy.

        Args:
            braid_url (str): URL of Braid server.
            use_zmq (bool): Use ZeroMQ for data streaming.
            topic (str): Topic for ZeroMQ socket.
        """
        # requests
        self.braid_url = braid_url
        self.session = None
        self.r = None

        # zmq
        self.socket = None
        self.port = port

    def connect(self):
        """
        Connects to the Braid server and initializes the session and socket for communication.

        This method establishes a connection to the Braid server by sending a GET request to the specified `braid_url`. It uses the `requests` library to create a session and send the request. The response from the server is then checked to ensure that the status code is `requests.codes.ok`.

        After the successful connection to the Braid server, the method initializes a `Publisher` object with the specified `port` and `topic`. The `Publisher` object is responsible for publishing messages to a ZeroMQ socket. Finally, the method calls the `connect()` method on the `Publisher` object to establish the connection to the ZeroMQ socket.

        This method does not take any parameters.

        This method does not return any value.
        """
        # requests
        self.session = requests.Session()
        r = self.session.get(self.braid_url)
        assert r.status_code == requests.codes.ok

        # zmq
        self.socket = Publisher(port=self.port, topic="braid_proxy")
        self.socket.connect()

    def run(self):
        """
        Run the main loop of the BraidProxy.

        This method connects to the Braid server and starts streaming events from it. It continuously iterates over the
        event stream, parsing each chunk of data and publishing it to the socket.

        Returns:
            None. The method does not return anything.

        Raises:
            requests.RequestException: If there is an error connecting to the Braid server or retrieving the event
                stream. The error message is logged.

        """
        events_url = self.braid_url + "events"
        try:
            r = self.session.get(
                events_url, stream=True, headers={"Accept": "text/event-stream"}
            )
            r.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to get events stream from braid server: {e}")
            return

        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            data = self.parse_chunk(chunk)
            self.socket.publish(data)

        self.close()

    def close(self):
        """
        Close the connection to the Braid server.

        This method closes the socket and session used to communicate with the Braid server. It also logs a message
        indicating that the connection has been closed.

        Parameters:
            None

        Returns:
            None
        """
        self.socket.close()
        self.session.close()
        logger.info("Closed connection to Braid server.")

    def parse_chunk(self, chunk: str) -> Optional[Dict[str, Any]]:
        """
        Parse a chunk of data received from the Braid server.

        Args:
            chunk (str): The raw chunk of data to parse.

        Returns:
            Optional[Dict]: The parsed data as a dictionary, or None if parsing fails.
        """
        DATA_PREFIX = "data: "
        lines = chunk.strip().split("\n")
        if (
            len(lines) != 2
            or lines[0] != "event: braid"
            or not lines[1].startswith(DATA_PREFIX)
        ):
            print(f"Unexpected chunk format: {chunk}")
            return None
        buf = lines[1][len(DATA_PREFIX) :]
        try:
            return json.loads(buf)
        except json.JSONDecodeError as e:
            print(f"Failed to decode JSON data: {e}")
            return None
