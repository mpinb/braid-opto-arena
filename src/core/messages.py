import zmq
from src.utils.log_config import setup_logging

logger = setup_logging(logger_name="Messages", level="INFO", color="cyan")


class Publisher:
    """
    A class for publishing messages over ZeroMQ publish-subscribe pattern.

    Attributes:
        port (int): The port to bind the ZeroMQ publisher socket to.
        topic (str): The topic to publish messages under.
    """

    def __init__(self, port=5555, topic=""):
        """
        Initialize a Publisher object.

        Args:
            port (int): The port to bind the ZeroMQ publisher socket to.
            topic (str): The topic to publish messages under.
        """
        self.port = port
        self.topic = topic

    def connect(self):
        """
        Connect the Publisher object to the ZeroMQ publisher socket.
        """
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(f"tcp://*:{self.port}")

    def publish(self, msg):
        """
        Publish a message with the specified topic.

        Args:
            msg (str): The message to publish.
        """
        self.socket.send_string(f"{self.topic} {msg}")
        logger.debug(f"Published message on topic '{self.topic}': {msg}")

    def close(self):
        """
        Close the ZeroMQ publisher socket and terminate the context.
        """
        self.socket.close()
        self.context.term()
        logger.info("Closed publisher socket and terminated context.")


class Subscriber:
    """
    A class representing a ZeroMQ subscriber.

    This class provides methods for connecting to a ZeroMQ subscriber socket,
    receiving messages, and closing the socket.

    Attributes:
        port (int): The port to bind the ZeroMQ subscriber socket to.
        topic (str): The topic to subscribe to.
    """

    def __init__(self, port=5555, topic=""):
        """
        Initialize a Subscriber object.

        Args:
            port (int): The port to bind the ZeroMQ subscriber socket to.
            topic (str): The topic to subscribe to.
        """
        self.port = port
        self.topic = topic

    def connect(self):
        """
        Connect the Subscriber object to the ZeroMQ subscriber socket.
        """
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.setsockopt_string(zmq.SUBSCRIBE, self.topic)
        self.socket.connect(f"tcp://*:{self.port}")

    def receive(self, block=False):
        """
        Receive a message from the subscriber socket.

        Args:
            block (bool): Whether to block until a message is received.

        Returns:
            tuple: A tuple containing the topic and the actual message.
                   If no message is received and block is False, returns (None, None).
                   If there is an error parsing the message, returns (None, None).
        """
        try:
            # Receive the message, with or without blocking based on the 'block' parameter
            if block:
                message = self.socket.recv_string()
            else:
                message = self.socket.recv_string(flags=zmq.NOBLOCK)
            # Split the message into topic and actual message
            topic, actual_message = message.split(" ", 1)
            logger.debug(f"Received message: {message}")
            return topic, actual_message
        except zmq.Again:
            # logger.debug("No message received yet: %s", e)
            return None, None
        except ValueError as e:
            logger.error("Error parsing message: %s", e)
            return None, None
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return None, None

    def close(self):
        """
        Close the ZeroMQ subscriber socket and terminate the context.
        """
        self.socket.close()
        self.context.term()
        logger.info("Closed subscriber socket and terminated context.")
