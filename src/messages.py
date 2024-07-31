import time

import zmq
from modules.utils.log_config import setup_logging

logger = setup_logging(logger_name="Messages", level="INFO", color="cyan")


class Publisher:
    def __init__(self, pub_port, handshake_port):
        self.context = zmq.Context()

        # Publisher socket
        self.pub_socket = self.context.socket(zmq.PUB)
        self.pub_socket.bind(f"tcp://*:{pub_port}")

        # Handshake socket
        self.rep_socket = self.context.socket(zmq.REP)
        self.rep_socket.bind(f"tcp://*:{handshake_port}")

    def wait_for_subscriber(self):
        # Wait for a handshake message from subscriber
        try:
            message = self.rep_socket.recv_string()  # Non-blocking receive
            if message == "Hello":
                self.rep_socket.send_string("Welcome")
                logger.info("Handshake completed with a subscriber.")
        except zmq.Again as e:
            logger.warning(f"{e} No handshake request received yet.")

    def publish(
        self,
        msg,
        topic="",
    ):
        self.pub_socket.send_string(f"{topic} {msg}")
        logger.debug(f"Published message on topic '{topic}': {msg}")

    def close(self):
        self.pub_socket.close()
        self.rep_socket.close()
        self.context.term()
        logger.info("Closed publisher sockets and terminated context.")


class Subscriber:
    def __init__(
        self,
        pub_port,
        handshake_port,
        server_ip="localhost",
        retry_attempts=5,
        retry_timeout=5,
    ):
        self.context = zmq.Context()
        self.retry_attempts = retry_attempts
        self.retry_timeout = retry_timeout

        # Subscriber socket
        self.sub_socket = self.context.socket(zmq.SUB)
        self.sub_socket.connect(f"tcp://{server_ip}:{pub_port}")

        # Handshake socket
        self.req_socket = self.context.socket(zmq.REQ)
        self.req_socket.connect(f"tcp://{server_ip}:{handshake_port}")

    def handshake(self):
        for _ in range(self.retry_attempts):
            try:
                # Send handshake message
                self.req_socket.send_string("Hello")
                reply = self.req_socket.recv_string()
                if reply == "Welcome":
                    logger.info("Handshake successful.")
                    return True
                else:
                    logger.warning("Handshake failed. Unexpected reply.")
            except zmq.ZMQError as e:
                logger.error(f"Handshake error: {e}")
            time.sleep(self.retry_timeout)  # wait before retrying
        logger.error("Handshake failed after maximum retry attempts.")

        return False

    def subscribe(self, topic=""):
        self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, topic)
        logger.info(f"Subscribed to topic '{topic}'.")

    def receive(self, block=False):
        try:
            # Receive the message, with or without blocking based on the 'block' parameter
            message = self.sub_socket.recv_string(flags=0 if block else zmq.NOBLOCK)

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
        self.sub_socket.close()
        self.req_socket.close()
        self.context.term()
        logger.info("Closed subscriber sockets and terminated context.")
