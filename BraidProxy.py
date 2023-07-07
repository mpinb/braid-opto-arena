#!/usr/bin/env python

# This script listens to the HTTP JSON Event Stream of flydra2 and transmits
# pose information over UDP in a simple text format.

# This is an example of listening for the live stream of flydra2. In version 1
# of the flydra2 pose api, in addition to the `Update` events, flydra2 also has
# `Birth` and `Death` events. The `Birth` event returns the same data as an
# `Update` event, whereas the `Death` event sends just `obj_id`.

import argparse
import json

import requests

DATA_PREFIX = "data: "


class Flydra2Proxy:
    def __init__(
        self,
        msg_queue,
        kill_event,
        flydra2_url="http://0.0.0.0:8397/",
    ):
        self.flydra2_url = flydra2_url
        self.session = requests.session()
        self.msg_queue = msg_queue
        self.kill_event = kill_event
        r = self.session.get(self.flydra2_url)
        assert r.status_code == requests.codes.ok

    def run(self):
        events_url = self.flydra2_url + "events"
        r = self.session.get(
            events_url,
            stream=True,
            headers={"Accept": "text/event-stream"},
        )
        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            data = parse_chunk(chunk)
            # print('chunk value: %r'%data)
            version = data.get("v", 1)  # default because missing in first release
            assert version == 2  # check the data version

            try:
                self.msg_queue.put(data["msg"])
            except KeyError:
                continue


def parse_chunk(chunk):
    lines = chunk.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "event: braid"
    assert lines[1].startswith(DATA_PREFIX)
    buf = lines[1][len(DATA_PREFIX) :]
    data = json.loads(buf)
    return data


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--flydra2-url", default="http://127.0.0.1:8397/", help="URL of flydra2 server"
    )

    parser.add_argument(
        "--udp-port", type=int, default=1234, help="UDP port to send pose information"
    )
    parser.add_argument(
        "--udp-host",
        type=str,
        default="127.0.0.1",
        help="UDP host to send pose information",
    )
    args = parser.parse_args()
    flydra2 = Flydra2Proxy(args.flydra2_url)
    flydra2.run(udp_host=args.udp_host, udp_port=args.udp_port)


if __name__ == "__main__":
    main()
