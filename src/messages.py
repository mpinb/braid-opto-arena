import zmq


class Publisher:
    def __init__(self, port):
        self.port = port
        self.context = None
        self.socket = None

    def __enter__(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind(f"tcp://*:{self.port}")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def send(self, message):
        if self.socket is None:
            raise RuntimeError(
                "Publisher is not initialized. Use with statement or call __enter__ method."
            )
        self.socket.send_string(message)

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        if self.context is not None:
            self.context.term()
            self.context = None


class Subscriber:
    def __init__(self, port, topic=""):
        self.port = port
        self.topic = topic
        self.context = None
        self.socket = None

    def __enter__(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.setsockopt_string(zmq.SUBSCRIBE, self.topic)
        self.socket.connect(f"tcp://127.0.0.1:{self.port}")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def receive(self):
        if self.socket is None:
            raise RuntimeError(
                "Subscriber is not initialized. Use with statement or call __enter__ method."
            )
        return self.socket.recv_string().split(' ', 1)

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        if self.context is not None:
            self.context.term()
            self.context = None
