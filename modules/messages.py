import logging
import time

import zmq

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(filename)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


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
                logging.info("Handshake completed with a subscriber.")
        except zmq.Again as e:
            logging.warning(f"{e} No handshake request received yet.")

    def publish(
        self,
        msg,
        topic="",
    ):
        self.pub_socket.send_string(f"{topic} {msg}")
        logging.debug(f"Published message on topic '{topic}': {msg}")

    def close(self):
        self.pub_socket.close()
        self.rep_socket.close()
        self.context.term()
        logging.info("Closed publisher sockets and terminated context.")


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
                    logging.info("Handshake successful.")
                    return True
                else:
                    logging.warning("Handshake failed. Unexpected reply.")
            except zmq.ZMQError as e:
                logging.error(f"Handshake error: {e}")
            time.sleep(self.retry_timeout)  # wait before retrying
        logging.error("Handshake failed after maximum retry attempts.")

        return False

    def subscribe(self, topic=""):
        self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, topic)
        logging.info(f"Subscribed to topic '{topic}'.")

    def receive(self, block=False):
        try:
            if block:
                message = self.sub_socket.recv_string()
            else:
                message = self.sub_socket.recv_string(zmq.NOBLOCK)

            topic, actual_message = message.split(" ", 1)
            logging.debug(f"Received message: {message}")
            return topic, actual_message

        except zmq.Again:
            logging.debug("No message received yet.")
            return None, None

    def close(self):
        self.sub_socket.close()
        self.req_socket.close()
        self.context.term()
        logging.info("Closed subscriber sockets and terminated context.")
