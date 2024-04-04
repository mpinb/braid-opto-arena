import pygame
import requests
import json
from collections import deque
import multiprocessing as mp
import numpy as np

KILL_EVENT = mp.Event()
HEADING = mp.Queue()


def parse_chunk(chunk):
    """function to parse incoming chunks from the flydra2 server

    Args:
        chunk (_type_): _description_

    Returns:
        data: a dict-formatted data object
    """
    DATA_PREFIX = "data: "
    lines = chunk.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "event: braid"
    assert lines[1].startswith(DATA_PREFIX)
    buf = lines[1][len(DATA_PREFIX) :]
    data = json.loads(buf)
    return data


def stimuli(HEADING):
    # Initialize pygame
    pygame.init()
    screen = pygame.display.set_mode((640, 128), pygame.NOFRAME)
    clock = pygame.time.Clock()

    while not KILL_EVENT.is_set():
        try:
            heading = HEADING.get_nowait()
        except mp.queues.Empty:
            pass

        pygame.display.flip()
        clock.tick(60)


# Connect to flydra2 proxy
flydra2_url = "http://0.0.0.0:8397/"
session = requests.Session()
r = session.get(flydra2_url)
assert r.status_code == requests.codes.ok
events_url = r.url + "events"

# data deque
heading_deque = deque(maxlen=10)

# main loop
with session.get(events_url, stream=True, headers={"Accept": "text/event-stream"}) as r:
    for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
        data = parse_chunk(chunk)

        try:
            msg_dict = data["msg"]["Update"]
        except KeyError:
            continue

        heading_deque.append((msg_dict["x"], msg_dict["y"]))

        if len(heading_deque) == 10:
            x0 = heading_deque[0][0]
            y0 = heading_deque[0][1]
            x1 = heading_deque[-1][0]
            y1 = heading_deque[-1][1]

            heading = np.arctan2(y1 - y0, x1 - x0)
