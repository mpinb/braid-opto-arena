import argparse
import json
import os
import subprocess
import time
from collections import deque

import numpy as np

from modules.messages import Publisher
from modules.utils.config_utils import read_parameters_file
from modules.utils.csv_writer import CsvWriter
from modules.utils.file_utils import copy_files_to_folder
from modules.utils.flydra_proxy import Flydra2Proxy
from modules.utils.folder_utils import check_braid_running
from modules.utils.hardware_utils import (
    create_arduino_device,
    initialize_backlighting_power_supply,
)
from modules.utils.opto_utils import check_position, trigger_opto
from modules.utils.video_utils import get_video_output_folder


def main(params_file: str, root_folder: str, args: argparse.Namespace):
    """Main BraidTrigger function. Starts up all processes and triggers.
    Loop over data incoming from the flydra2 proxy and tests if a trigger should be sent.

    Args:
        params_file (str): a path to the params.toml file
        root_folder (str): the root folder where the experiment folder will be created
    """

    # Load params
    params = read_parameters_file(params_file)

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
    heading_direction = deque(maxlen=5)

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

            # Calculate heading direction
            heading_direction.append(np.arctan2(pos["yvel"], pos["xvel"]))
            pos["heading_direction"] = np.nanmean(heading_direction)

            if args.realtime_plotting:
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
