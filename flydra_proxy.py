import json
import logging
import multiprocessing as mp
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


def flydra_proxy(
    flydra2_url: str,
    out_queue: mp.Queue,
    kill_event: mp.Event,
    barrier: mp.Barrier,
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
