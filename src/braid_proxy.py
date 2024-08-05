import requests
import json

DATA_PREFIX = "data: "


def connect_to_braid_proxy(braid_url: str):
    # connect and check
    session = requests.session()
    r = session.get(braid_url)
    assert r.status_code == requests.codes.ok

    # start braid proxy
    events_url = braid_url + "events"
    r = session.get(
        events_url,
        stream=True,
        headers={"Accept": "text/event-stream"},
    )

    return r


def parse_chunk(chunk):
    lines = chunk.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "event: braid"
    assert lines[1].startswith(DATA_PREFIX)
    buf = lines[1][len(DATA_PREFIX) :]
    data = json.loads(buf)
    return data
