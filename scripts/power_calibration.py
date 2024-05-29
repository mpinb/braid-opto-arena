#!/usr/bin/env python

# This script listens to the HTTP JSON Event Stream of flydra2 and transmits
# pose information over UDP in a simple text format.

# This is an example of listening for the live stream of flydra2. In version 1
# of the flydra2 pose api, in addition to the `Update` events, flydra2 also has
# `Birth` and `Death` events. The `Birth` event returns the same data as an
# `Update` event, whereas the `Death` event sends just `obj_id`.

from __future__ import print_function

import argparse
import csv
import json
from queue import Queue
from threading import Thread

import requests
from ThorlabsPM100 import USBTMC, ThorlabsPM100

DATA_PREFIX = "data: "


# create a threaded csv writer that creates a csv file, accepts a dict over a queue and writes to a csv file
# if it's the first dict, write the header first
def csv_writer(csv_file, queue):
    with open(csv_file, "a+") as csvfile:
        # get first data from queue
        first_data = queue.get()

        # open csv writer and write header and first_data
        w = csv.DictWriter(csvfile, fieldnames=first_data.keys())
        w.writeheader()
        w.writerow(first_data)

        # loop until break
        while True:
            data = queue.get()
            if data is None:
                break
            w.writerow(data)
            csvfile.flush()


class Flydra2Proxy:
    def __init__(self, flydra2_url):
        self.flydra2_url = flydra2_url
        self.session = requests.session()
        r = self.session.get(self.flydra2_url)
        assert r.status_code == requests.codes.ok

        self.queue = Queue()
        self.connect_to_power_meter()
        self.connect_to_csv_writer()

    def connect_to_csv_writer(self, csv_file="./power_calibration.csv"):
        # start csv writer as background thread
        csv_writer_thread = Thread(target=csv_writer, args=(csv_file, self.queue))
        csv_writer_thread.daemon = True
        csv_writer_thread.start()

    def connect_to_power_meter(self, addr: str = "/dev/usbtmc1"):
        inst = USBTMC(device=addr)
        self.power_meter = ThorlabsPM100(inst=inst)

    def run(self, udp_host, udp_port):
        addr = (udp_host, udp_port)
        print("sending flydra data to UDP %s" % (addr,))
        events_url = self.flydra2_url + "events"
        r = self.session.get(
            events_url,
            stream=True,
            headers={"Accept": "text/event-stream"},
        )
        try:
            for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
                data = parse_chunk(chunk)
                # print('chunk value: %r'%data)
                version = data.get("v", 1)  # default because missing in first release
                assert version == 2  # check the data version

                try:
                    update_dict = data["msg"]["Update"]
                    update_dict["power"] = self.power_meter.read
                    self.queue.put(update_dict)
                except KeyError:
                    continue

        except KeyboardInterrupt:
            self.queue.put(None)
            print("exiting")


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
