import csv
import filecmp
import json
import logging
import os
import pathlib
import random
import shutil
import socket
import time

import git
import requests
import serial
import tomllib
from rspowersupply import PowerSupply
from tqdm.contrib.concurrent import thread_map


def copy_files_with_progress(src_folder, dest_folder):
    def copy_file(src_file_path, dest_file_path):
        shutil.copy2(src_file_path, dest_file_path)

        if filecmp.cmp(src_file_path, dest_file_path, shallow=False):
            logging.debug(f"File {src_file_path} copied successfully.")
            os.remove(src_file_path)

    # Get a list of all files in the source folder
    files = [
        f for f in os.listdir(src_folder) if os.path.isfile(os.path.join(src_folder, f))
    ]

    src_file_paths = [os.path.join(src_folder, file) for file in files]
    dest_file_paths = [os.path.join(dest_folder, file) for file in files]

    # Make sure the destination folder exists
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    thread_map(copy_file, src_file_paths, dest_file_paths, max_workers=4)

    if len(os.listdir(src_folder)) == 0:
        os.rmdir(src_folder)


def check_braid_folder(root_folder: str) -> str:
    """A simple function to check (and block) until a folder is created.

    Args:
        root_folder (str): the root location where we expect the .braid folder to be created.

    Returns:
        str: the path to the .braid folder.
    """
    p = pathlib.Path(root_folder)
    curr_braid_folder = list(p.glob("*.braid"))

    # loop and test as long as a folder doesn't exist
    if len(curr_braid_folder) == 0:
        logging.info(f"Waiting for .braid folder to be created in {root_folder}....")

    while len(curr_braid_folder) == 0:
        time.sleep(1)
        p = pathlib.Path(root_folder)
        curr_braid_folder = list(p.glob("*.braid"))

    logging.info(f"\nFolder {curr_braid_folder[0].as_posix()} found.")

    return curr_braid_folder[0].as_posix()


def read_parameters_file(params_file: str) -> dict:
    with open(params_file, "rb") as f:
        params = tomllib.load(f)
    return params


def check_braid_running(root_folder: str, debug: bool) -> str:
    if not debug:
        return check_braid_folder(root_folder)
    else:
        os.makedirs("test/", exist_ok=True)
        return "test/"


def copy_files_to_folder(folder: str, file: str):
    shutil.copy(file, folder)
    with open(os.path.join(folder, "params.toml"), "w") as f:
        f.write(
            f"commit = {git.Repo(search_parent_directories=True).head.commit.hexsha}"
        )


def initialize_backlighting_power_supply(port="/dev/powersupply", voltage=30):
    try:
        ps = PowerSupply(port=port)
        ps.set_voltage(voltage)
    except RuntimeError:
        raise RuntimeError("Backlight power supply not connected.")


def create_arduino_device(port: str, baudrate: int = 9600) -> serial.Serial:
    return serial.Serial(port, baudrate=baudrate, timeout=1)


class CsvWriter:
    def __init__(self, filename):
        self.filename = filename
        self.csv_file = open(filename, "a+")
        self.write_header = True
        self.csv_writer = csv.writer(self.csv_file)

    def write(self, data):
        if self.write_header:
            self.csv_writer.writerow(data.keys())
            self.write_header = False
        self.csv_writer.writerow(data.values())
        self.csv_file.flush()

    def check_header(self):
        if os.stat(self.filename).st_size > 0:
            self.write_header = False

    def close(self):
        self.csv_file.close()


class Flydra2Proxy:
    def __init__(self, flydra2_url: str = "http://10.40.80.6:8397/"):
        self.flydra2_url = flydra2_url
        self.session = requests.session()
        r = self.session.get(self.flydra2_url)
        assert r.status_code == requests.codes.ok

    def data_stream(self):
        """Generator that yields parsed data chunks from the event stream."""
        events_url = self.flydra2_url + "events"
        r = self.session.get(
            events_url, stream=True, headers={"Accept": "text/event-stream"}
        )
        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            data = self.parse_chunk(chunk)
            if data:
                yield data

    def parse_chunk(self, chunk):
        """Parses a chunk and extracts the data."""
        DATA_PREFIX = "data: "
        lines = chunk.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "event: braid"
        assert lines[1].startswith(DATA_PREFIX)
        buf = lines[1][len(DATA_PREFIX) :]
        data = json.loads(buf)
        return data

    def send_to_udp(self, udp_host, udp_port):
        """Send parsed data to UDP after verifying version."""
        addr = (udp_host, udp_port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for data in self.data_stream():
            version = data.get("v", 1)  # default because missing in first release
            assert version == 2  # check the data version
            try:
                update_dict = data["msg"]["Update"]
            except KeyError:
                continue
            msg = "%s, %s, %s" % (update_dict["x"], update_dict["y"], update_dict["z"])
            msg = msg.encode("ascii")
            sock.sendto(msg, addr)


def _get_opto_trigger_params(trigger_params: dict):
    if random.random() < trigger_params["sham_perc"]:
        logging.debug("Sham opto.")
        return 0, 0, 0
    else:
        return (
            trigger_params["stim_duration"],
            trigger_params["stim_intensity"],
            trigger_params["stim_frequency"],
        )


def trigger_opto(opto_trigger_board: serial.Serial, trigger_params: dict, pos: dict):
    stim_duration, stim_intensity, stim_frequency = _get_opto_trigger_params(
        trigger_params
    )

    opto_trigger_board.write(
        f"<{stim_duration},{stim_intensity},{stim_frequency}>".encode()
    )
    pos["stim_duration"] = stim_duration
    pos["stim_intensity"] = stim_intensity
    pos["stim_frequency"] = stim_frequency
    return pos


def check_position(pos, trigger_params):
    radius = (pos["x"] ** 2 + pos["y"] ** 2) ** 0.5
    if trigger_params["type"] == "radius":
        in_position = (
            radius < trigger_params["min_radius"]
            and trigger_params["zmin"] <= pos["z"] <= trigger_params["zmax"]
        )
    elif trigger_params["type"] == "zone":
        # Check if object is in the trigger zone
        in_position = (
            0.1 <= pos["z"] <= 0.2
            and -0.084 <= pos["x"] <= 0.065
            and -0.054 <= pos["y"] <= 0.095
        )

    return in_position


def get_video_output_folder(
    braid_folder: str, base_folder: str = "/home/buchsbaum/mnt/DATA/Videos/"
):
    base_folder = os.path.splitext(os.path.basename(braid_folder))[0]
    return os.path.join((base_folder, braid_folder))
