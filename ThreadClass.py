from queue import Queue
import threading


class ThreadClass:
    def __init__(
        self,
        queue: Queue,
        kill_event: threading.Event,
        barrier: threading.Barrier,
        params: dict,
    ) -> None:
        # Threading stuff
        self.queue = queue
        self.kill_event = kill_event
        self.barrier = barrier
        self.params = params
