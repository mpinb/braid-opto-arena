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

    def send(self, topic, message):
        if self.socket is None:
            raise RuntimeError(
                "Publisher is not initialized. Use `with` statement or call __enter__ method."
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
    def __init__(self, address, port, topics):
        self.address = address
        self.port = port
        self.topics = topics if isinstance(topics, list) else [topics]
        self.context = None
        self.socket = None

    def __enter__(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect(f"tcp://{self.address}:{self.port}")
        for topic in self.topics:
            self.socket.setsockopt_string(zmq.SUBSCRIBE, topic)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def receive(self, timeout=None):
        if self.socket is None:
            raise RuntimeError(
                "Subscriber is not initialized. Use with statement or call __enter__ method."
            )
        if timeout is not None:
            if self.socket.poll(timeout * 1000) == 0:
                return None
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
