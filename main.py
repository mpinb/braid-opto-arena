import argparse
import os
import shutil
import git
import requests
import tomllib
import json
from modules.messages import Publisher
from modules.utils import check_braid_folder
from modules.rspowersupply import PowerSupply
import serial
import time
import socket
import random
import csv
import subprocess

PSU_VOLTAGE = 30


def read_parameters(params_file: str) -> dict:
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


def initialize_backlighting_power_supply(port="/dev/powersupply"):
    try:
        ps = PowerSupply(port=port)
        ps.set_voltage(PSU_VOLTAGE)
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


def main(params_file: str, root_folder: str, args: argparse.Namespace):
    """Main BraidTrigger function. Starts up all processes and triggers.
    Loop over data incoming from the flydra2 proxy and tests if a trigger should be sent.

    Args:
        params_file (str): a path to the params.toml file
        root_folder (str): the root folder where the experiment folder will be created
    """

    # Load params
    params = read_parameters(params_file)

    # Check if braidz is running (see if folder was created)
    params["folder"] = check_braid_running(root_folder, args.debug)

    # Copy the params file to the experiment folder
    copy_files_to_folder(params["folder"], params_file)

    # Set power supply voltage (for backlighting)
    initialize_backlighting_power_supply()

    # Connect to arduino
    if args.opto:
        opto_trigger_board = create_arduino_device(
            port=params["arduino_devices"]["opto_trigger"]
        )

    # Connect to flydra2 proxy
    braid_proxy = Flydra2Proxy()

    # create data publisher
    pub = Publisher(pub_port=5556, handshake_port=5557)

    if args.realtime_plotting:
        import zmq

        context = zmq.Context()
        pub_plot = context.socket(zmq.PUB)
        pub_plot.bind("tcp://*:12345")
        subprocess.Popen(["python", "modules/plotting.py"])

    # Connect to cameras
    if args.highspeed:
        params["video_save_folder"] = get_video_output_folder(params["folder"])
        # start camera here
        pub.wait_for_subscriber()
        pub.publish("", params["video_save_folder"])

    if args.static or args.looming or args.grating:
        subprocess.Popen("python modules/stimuli.py")
        pub.wait_for_subscriber()
        pub.publish("stimuli", "start")
        

    trigger_params = params["trigger_params"]

    csv_writer = CsvWriter(os.path.join(params["folder"], "opto.csv"))

    # initialize main loop parameters
    obj_ids = []
    obj_birth_times = {}
    last_trigger_time = time.time()
    ntrig = 0

    # Start main loop
    try:
        for data in braid_proxy.data_stream():
            tcall = time.time()  # Get current time

            try:
                msg_dict = data["msg"]
            except KeyError:
                continue

            # Check for first "birth" message
            if "Birth" in msg_dict:
                curr_obj_id = msg_dict["Birth"]["obj_id"]
                obj_ids.append(curr_obj_id)
                obj_birth_times[curr_obj_id] = tcall
                continue

            # Check for "update" message
            elif "Update" in msg_dict:
                curr_obj_id = msg_dict["Update"]["obj_id"]
                if curr_obj_id not in obj_ids:
                    obj_ids.append(curr_obj_id)
                    obj_birth_times[curr_obj_id] = tcall
                    continue

            # Check for "death" message
            elif "Death" in msg_dict:
                curr_obj_id = msg_dict["Death"]
                if curr_obj_id in obj_ids:
                    obj_ids.remove(curr_obj_id)
                continue

            else:
                continue

            # if the trajectory is too short, skip
            if (tcall - obj_birth_times[curr_obj_id]) < trigger_params[
                "min_trajectory_time"
            ]:
                # logging.warning(f"Trajectory too short for object {curr_obj_id}")
                continue

            # if the trigger interval is too short, skip
            if tcall - last_trigger_time < trigger_params["min_trigger_interval"]:
                # logging.warning(f"Trigger interval too short for object {curr_obj_id}")
                continue

            # Get position and radius
            pos = msg_dict["Update"]
            pub_plot.send_string(f"{pos['x']} {pos['y']} {pos['z']}")

            if check_position(pos, trigger_params):
                # Update last trigger time
                ntrig += 1
                last_trigger_time = tcall

                # Add trigger time to dict
                pos["trigger_time"] = last_trigger_time
                pos["ntrig"] = ntrig

                # Opto Trigger
                if args.opto:
                    pos = trigger_opto(opto_trigger_board, trigger_params, pos)

                if args.highspeed:
                    pos["timestamp"] = tcall
                    pub.publish("", json.dumps(pos).encode("utf-8"))

                if args.stimuli:
                    pass

                # Write data to csv
                csv_writer.write(pos)

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(processName)s: %(asctime)s - %(message)s",
    )

    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--opto", action="store_true", default=False)
    parser.add_argument("--static", action="store_true", default=False)
    parser.add_argument("--looming", action="store_true", default=False)
    parser.add_argument("--grating", action="store_true", default=False)
    parser.add_argument("--highspeed", action="store_true", default=False)
    parser.add_argument("--debug", action="store_true", default=True)
    parser.add_argument("--realtime_plotting", action="store_true", default=True)
    args = parser.parse_args()

    for arg in vars(args):
        logging.info(f"{arg}: {getattr(args, arg)}")

    # Start main function
    print("Starting main function.")
    main(
        params_file="./static/params.toml",
        root_folder="/home/buchsbaum/mnt/DATA/Experiments/",
        args=args,
    )
