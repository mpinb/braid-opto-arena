#!/usr/bin/env python

# This script listens to the HTTP JSON Event Stream of flydra2 and transmits
# pose information over UDP in a simple text format.

# This is an example of listening for the live stream of flydra2. In version 1
# of the flydra2 pose api, in addition to the `Update` events, flydra2 also has
# `Birth` and `Death` events. The `Birth` event returns the same data as an
# `Update` event, whereas the `Death` event sends just `obj_id`.

from __future__ import print_function
import argparse
import requests
import json
import time
import zmq

DATA_PREFIX = "data: "


class Flydra2Proxy:
    def __init__(self, flydra2_url):
        self.flydra2_url = flydra2_url
        self.session = requests.session()
        r = self.session.get(self.flydra2_url)
        assert r.status_code == requests.codes.ok

    def run(self, tcp_addr):
        print("sending flydra data to tcp %s" % (tcp_addr,))
        context = zmq.Context()
        socket = context.socket(zmq.PUB)
        socket.bind("tcp://127.0.0.1:5555")

        # wait for socket to initialize properly
        time.sleep(5)

        # send the folder to write the videos to
        socket.send("/tmp/".encode("utf-8"))

        events_url = self.flydra2_url + "events"
        r = self.session.get(
            events_url,
            stream=True,
            headers={"Accept": "text/event-stream"},
        )

        start_time = time.time()

        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            data = parse_chunk(chunk)
            # print('chunk value: %r'%data)
            version = data.get("v", 1)  # default because missing in first release
            assert version == 3  # check the data version

            try:
                update_dict = data["msg"]["Update"]
                update_dict["timestamp"] = time.time()

            except KeyError:
                continue

            if time.time() - start_time > 10:
                socket.send(json.dumps(update_dict).encode("utf-8"))


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
        "--flydra2-url", default="http://10.40.80.6:8397/", help="URL of flydra2 server"
    )
    parser.add_argument(
        "--tcp-addr",
        type=str,
        default="127.0.0.1:5555",
        help="TCP address to send pose information",
    )

    args = parser.parse_args()
    flydra2 = Flydra2Proxy(args.flydra2_url)
    flydra2.run(tcp_addr=args.tcp_addr)


if __name__ == "__main__":
    main()
