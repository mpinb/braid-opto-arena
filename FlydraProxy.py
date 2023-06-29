import json
import logging
import time
from queue import Queue
from threading import Barrier, Event

import requests

from ThreadClass import ThreadClass

DATA_PREFIX = "data: "


class FlydraProxy(ThreadClass):
    def __init__(
        self,
        url: str,
        queue: Queue,
        kill_event: Event,
        barrier: Barrier,
        params: dict,
        *args,
        **kwargs,
    ) -> None:
        super(FlydraProxy, self).__init__(
            queue, kill_event, barrier, params, *args, **kwargs
        )

        # Initialize the session
        self.session = requests.session()
        self.r = self.session.get(url)
        assert self.r.status_code == requests.codes.ok

        # Connect to the event stream
        self.events_url = url + "events"
        self.r = self.session.get(
            self.events_url,
            stream=True,
            headers={"Accept": "text/event-stream"},
        )

    def run(self):
        # Wait for all processes/threads to start
        logging.debug("Waiting for barrier.")
        self.barrier.wait()

        # Start the event stream
        logging.debug("Starting main loop.")
        for chunk in self.r.iter_content(chunk_size=None, decode_unicode=True):
            # Check for kill event
            if self.kill_event.is_set():
                break

            # Process incoming data
            data = self._parse_chunk(chunk)

            # Check the data version
            version = data.get("v", 1)
            assert version == 2

            # Put the data in the queue
            try:
                self.queue.put(data["msg"])
            except KeyError:
                continue

        self.queue.join()

    def _parse_chunk(self, chunk):
        lines = chunk.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "event: braid"
        assert lines[1].startswith(DATA_PREFIX)
        buf = lines[1][len(DATA_PREFIX) :]
        data = json.loads(buf)
        return data
