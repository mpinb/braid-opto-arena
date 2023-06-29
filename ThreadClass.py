from queue import Queue
import threading


class ThreadClass(threading.Thread):
    def __init__(
        self,
        queue: Queue | None,
        kill_event: threading.Event | None = None,
        barrier: threading.Barrier | None = None,
        params: dict | None = None,
        *args,
        **kwargs,
    ) -> None:
        super(ThreadClass, self).__init__(*args, **kwargs)

        # Threading stuff
        self.queue = queue
        self.kill_event = kill_event
        self.barrier = barrier
        self.params = params


if __name__ == "__main__":
    pass
