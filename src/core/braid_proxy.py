import asyncio
import aiohttp
import json
import zmq
import zmq.asyncio
from typing import Dict, Optional, AsyncGenerator


class BraidProxy:
    """
    A proxy class for interacting with a Braid server and optionally publishing data via ZeroMQ.

    This class provides methods to connect to a Braid server, stream data from it,
    and optionally publish this data using ZeroMQ for other processes to consume.

    Attributes:
        Braid_url (str): The URL of the Braid server.
        use_zmq (bool): Whether to use ZeroMQ for publishing data.
        zmq_context (zmq.asyncio.Context): The ZeroMQ context (only if use_zmq is True).
        zmq_socket (zmq.asyncio.Socket): The ZeroMQ publisher socket (only if use_zmq is True).
        topic (str): The topic to use for ZeroMQ messages.
        session (aiohttp.ClientSession): The aiohttp session for making HTTP requests.
    """

    def __init__(
        self,
        Braid_url: str = "http://10.40.80.6:8397/",
        use_zmq: bool = False,
        topic: str = "braid",
    ):
        """
        Initialize the BraidProxy.

        Args:
            Braid_url (str): The URL of the Braid server.
            use_zmq (bool): Whether to use ZeroMQ for publishing data.
            topic (str): The topic to use for ZeroMQ messages.
        """
        self.Braid_url = Braid_url
        self.use_zmq = use_zmq
        self.zmq_context = zmq.asyncio.Context() if use_zmq else None
        self.zmq_socket = None
        self.topic = topic
        self.session = None

    async def __aenter__(self):
        """
        Async context manager entry point. Sets up the aiohttp session and ZeroMQ socket.

        Returns:
            BraidProxy: The initialized BraidProxy instance.
        """
        self.session = aiohttp.ClientSession()
        if self.use_zmq:
            self.zmq_socket = self.zmq_context.socket(zmq.PUB)
            self.zmq_socket.bind("tcp://*:8397")  # Adjust port as needed
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """
        Async context manager exit point. Cleans up resources.

        Args:
            exc_type: The type of the exception that caused the context to be exited.
            exc: The exception that caused the context to be exited.
            tb: The traceback for the exception.
        """
        await self.session.close()
        if self.zmq_socket:
            self.zmq_socket.close()

    async def connect(self):
        """
        Establish a connection to the Braid server.

        Raises:
            aiohttp.ClientError: If connection to the Braid server fails.
        """
        try:
            async with self.session.get(self.Braid_url) as response:
                response.raise_for_status()
        except aiohttp.ClientError as e:
            print(f"Failed to connect to Braid server: {e}")
            raise

    async def data_stream(self) -> AsyncGenerator[Dict, None]:
        """
        Stream data from the Braid server.

        If ZeroMQ is enabled, publishes the data to the ZeroMQ socket.
        Otherwise, yields the data.

        Yields:
            Dict: The parsed data from the Braid server.

        Raises:
            aiohttp.ClientError: If streaming from the Braid server fails.
        """
        events_url = f"{self.Braid_url}events"
        try:
            async with self.session.get(
                events_url, headers={"Accept": "text/event-stream"}
            ) as response:
                response.raise_for_status()
                async for chunk in response.content:
                    data = self.parse_chunk(chunk.decode())
                    if data:
                        if self.use_zmq:
                            await self.zmq_socket.send_string(
                                f"{self.topic} {json.dumps(data)}"
                            )
                        else:
                            yield data
        except aiohttp.ClientError as e:
            print(f"Failed to get events stream from Braid server: {e}")

    def parse_chunk(self, chunk: str) -> Optional[Dict]:
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

    async def run(self):
        """
        Run the main loop of the BraidProxy.

        This method connects to the Braid server and continuously streams data,
        publishing it via ZeroMQ if enabled.
        """
        await self.connect()
        async for _ in self.data_stream():
            pass  # Data is sent via ZMQ, no need to do anything here


async def main():
    """
    Main function to demonstrate the usage of BraidProxy.
    """
    async with BraidProxy(use_zmq=True, topic="braid_data") as proxy:
        await proxy.run()


if __name__ == "__main__":
    asyncio.run(main())
