import zmq


class Publisher:
    def __init__(self, port):
        self.port = port
        self.context = None
        self.socket = None

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

    def send(self, topic, message):
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
    def __init__(self, address, port, topics):
        self.address = address
        self.port = port
        self.topics = topics if isinstance(topics, list) else [topics]
        self.context = None
        self.socket = None

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

    def receive(self, timeout=None, blocking=True):
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
                return None

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
