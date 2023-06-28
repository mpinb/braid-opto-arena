import json
import logging
import multiprocessing as mp
import threading
from queue import Queue
import time

import requests

DATA_PREFIX = "data: "


def _parse_chunk(chunk):
    lines = chunk.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "event: braid"
    assert lines[1].startswith(DATA_PREFIX)
    buf = lines[1][len(DATA_PREFIX) :]
    data = json.loads(buf)
    return data


class FlydraProxy:
    def __init__(
        self,
        url: str,
        queue: Queue,
        kill_event: threading.Event,
        barrier: threading.Barrier,
    ) -> None:
        # Threading stuff
        self.queue = queue
        self.barrier = barrier
        self.kill_event = kill_event

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
        self.barrier.wait()

        # Start the event stream
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


def flydra_proxy(
    flydra2_url: str,
    out_queue: Queue,
    kill_event: threading.Event,
    barrier: threading.Barrier,
):
    session = requests.session()
    r = session.get(flydra2_url)
    assert r.status_code == requests.codes.ok

    # connect to the event stream
    events_url = flydra2_url + "events"
    r = session.get(
        events_url,
        stream=True,
        headers={"Accept": "text/event-stream"},
    )

    # wait for all processes to start
    barrier.wait()

    logging.info(f"Connected to {events_url}, strarting event stream.")
    try:
        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            # check for kill event
            if kill_event.is_set():
                break

            stime = time.time()

            data = _parse_chunk(chunk)

            version = data.get("v", 1)  # default because missing in first release
            assert version == 2  # check the data version

            try:
                out_queue.put(data["msg"])
            except KeyError:
                continue

            logging.debug(f"Queue size: {out_queue.qsize()}")
            logging.debug(f"Time to process chunk: {time.time() - stime:.3f}s")
    except KeyboardInterrupt:
        pass
