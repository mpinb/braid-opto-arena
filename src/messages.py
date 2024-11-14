# ./src/messages.py
import zmq
from typing import Optional, List, Union, Tuple


class Publisher:
    def __init__(self, port: int) -> None:
        """
        Initializes a Publisher object.

        Args:
            port (int): The port number to bind the socket to.

        Returns:
            None
        """
        self.port: int = port
        self.context: Optional[zmq.Context] = None
        self.socket: Optional[zmq.Socket] = None

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def initialize(self):
        if self.context is None:
            self.context = zmq.Context()
        if self.socket is None:
            self.socket = self.context.socket(zmq.PUB)
            self.socket.bind(f"tcp://*:{self.port}")

    def send(self, topic: str, message: str) -> None:
        """
        Sends a message to the specified topic.

        Args:
            topic (str): The topic to send the message to.
            message (str): The message to send.

        Raises:
            RuntimeError: If the Publisher is not initialized.

        Returns:
            None
        """
        if self.socket is None:
            raise RuntimeError(
                "Publisher is not initialized. Call initialize() method or use with statement."
            )
        self.socket.send_string(f"{topic} {message}")

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        if self.context is not None:
            self.context.term()
            self.context = None


class Subscriber:
    def __init__(self, address: str, port: int, topics: Union[str, List[str]]) -> None:
        """
        Initializes a Subscriber object.

        Args:
            address (str): The address to bind the socket to.
            port (int): The port number to bind the socket to.
            topics (Union[str, List[str]]): The topics to subscribe to.

        Returns:
            None
        """
        self.address: str = address
        self.port: int = port
        self.topics: List[str] = topics if isinstance(topics, list) else [topics]
        self.context: Optional[zmq.Context] = None
        self.socket: Optional[zmq.Socket] = None

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def initialize(self):
        if self.context is None:
            self.context = zmq.Context()
        if self.socket is None:
            self.socket = self.context.socket(zmq.SUB)
            self.socket.connect(f"tcp://{self.address}:{self.port}")
            for topic in self.topics:
                self.socket.setsockopt_string(zmq.SUBSCRIBE, topic)

    def receive(
        self, timeout: Optional[float] = None, blocking: bool = True
    ) -> Optional[Tuple[str, str]]:
        """
        Receives a message from the socket.

        Args:
            timeout (Optional[float]): The timeout value in seconds. If None, does not timeout.
            blocking (bool): Whether to block until a message is received.

        Returns:
            Optional[Tuple[str, str]]: The topic and content of the received message, or None if no message is available.
        """
        if self.socket is None:
            raise RuntimeError(
                "Subscriber is not initialized. Call initialize() method or use with statement."
            )

        if not blocking:
            try:
                message = self.socket.recv_string(flags=zmq.NOBLOCK)
                topic, content = message.split(" ", 1)
                return topic, content
            except zmq.Again:
                return None, None

        if timeout is not None:
            if self.socket.poll(timeout * 1000) == 0:
                return None, None

        message = self.socket.recv_string()
        topic, content = message.split(" ", 1)
        return topic, content

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        if self.context is not None:
            self.context.term()
            self.context = None
