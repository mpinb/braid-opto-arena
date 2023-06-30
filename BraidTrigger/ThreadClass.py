from queue import Queue
import threading


class ThreadClass(threading.Thread):
    """_summary_

    Args:
        threading (_type_): _description_
    """

    def __init__(
        self,
        queue: Queue | None,
        kill_event: threading.Event | None = None,
        barrier: threading.Barrier | None = None,
        params: dict | None = None,
        *args,
        **kwargs,
    ) -> None:
        """_summary_

        Args:
            queue (Queue | None): _description_
            kill_event (threading.Event | None, optional): _description_. Defaults to None.
            barrier (threading.Barrier | None, optional): _description_. Defaults to None.
            params (dict | None, optional): _description_. Defaults to None.
        """
        super(ThreadClass, self).__init__(*args, **kwargs)

        # Threading stuff
        self.queue = queue
        self.kill_event = kill_event
        self.barrier = barrier
        self.params = params


if __name__ == "__main__":
    pass
