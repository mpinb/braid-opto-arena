import logging
import os
import pathlib
import shutil
import threading
import time
import tomllib
from queue import Queue

import git
import serial

from BraidTrigger.CamerasManager import CamerasManager
from BraidTrigger.FlydraProxy import FlydraProxy
from BraidTrigger.OptoTrigger import OptoTrigger
from BraidTrigger.PositionTrigger import PositionTrigger
from BraidTrigger.VisualStimuli import VisualStimuli


def check_braid_folder(root_folder: str) -> str:
    p = pathlib.Path(root_folder)
    curr_braid_folder = list(p.glob("*.braid"))

    # loop and test as long as a folder doesn't exist
    if len(curr_braid_folder) == 0:
        print(f"Waiting for .braid folder to be created in {root_folder}....")

    while len(curr_braid_folder) == 0:
        time.sleep(1)
        p = pathlib.Path(root_folder)
        curr_braid_folder = list(p.glob("*.braid"))

    print(f"\nFolder {curr_braid_folder[0].as_posix()} found.")

    return curr_braid_folder[0].as_posix()


def main(params_file: str, root_folder: str):
    # Load params
    with open(params_file, "rb") as f:
        params = tomllib.load(f)

    # Check if braidz is running (see if folder was created)
    folder = check_braid_folder(root_folder)
    params["folder"] = folder
    # Copy the params file to the experiment folder
    shutil.copy(params_file, folder)
    with open(os.path.join(folder, "params.toml"), "w") as f:
        f.write(
            f"commit = {git.Repo(search_parent_directories=True).head.commit.hexsha}"
        )

    # Create all threading stuff
    data_queue = Queue()
    kill_event = threading.Event()

    # Start counting how many barriers we need
    num_barriers = 3  # 1 for main thread + 1 for FlydraProxy + 1 for PositionTrigger

    # Also count how many output queues we need
    num_out_queues = 0

    # Check if the opto is active
    if params["opto_params"]["active"]:
        num_barriers += 1
        num_out_queues += 1

    # Check if and how many cameras are working
    if params["highspeed"]["active"]:
        num_barriers + 1  # +1 for CamerasManager (each camera has it's own mp.barrier)
        num_out_queues += 1

    # Check if and how many visual stimuli are active
    if params["stim_params"]["static"]["active"]:
        num_barriers += 1  # +1 for the basic static stimuli

    if (
        params["stim_params"]["grating"]["active"]
        or params["stim_params"]["looming"]["active"]
    ):
        num_out_queues += 1

    # Create the barrier
    barrier = threading.Barrier(6)
    out_queues = [Queue() for _ in range(num_out_queues)]

    # Start FlydraProxy
    flydra_proxy = FlydraProxy(
        queue=data_queue,
        kill_event=kill_event,
        barrier=barrier,
        name="FlydraProxy",
    )

    # Start PositionTrigger
    position_trigger = PositionTrigger(
        out_queues=out_queues,
        queue=data_queue,
        kill_event=kill_event,
        barrier=barrier,
        params=params["trigger_params"],
        name="PositionTrigger",
    )

    # Start OptoTrigger
    opto_trigger = OptoTrigger(
        queue=out_queues[0],
        kill_event=kill_event,
        barrier=barrier,
        params=params,
        name="OptoTrigger",
    )

    # Start VisualStimuli
    visual_stimuli = VisualStimuli(
        queue=out_queues[1],
        kill_event=kill_event,
        barrier=barrier,
        params=params,
        name="VisualStimuli",
    )

    # Start CamerasManager
    cameras_manager = CamerasManager(
        queue=out_queues[2],
        kill_event=kill_event,
        barrier=barrier,
        params=params,
        name="CamerasManager",
    )

    # Start all threads
    flydra_proxy.start()
    position_trigger.start()
    opto_trigger.start()
    visual_stimuli.start()
    cameras_manager.start()

    # Wait for everything to start
    logging.debug("Waiting for all threads to start...")
    print(f"Main Thread parties: {barrier.parties}, n_waiting: {barrier.n_waiting}")
    barrier.wait()
    logging.info("Started all threads successfully.")

    # Main loop
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.debug("KeyboardInterrupt received. Stopping all threads...")
        kill_event.set()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG, format="%(threadName)s: %(asctime)s - %(message)s"
    )
    main(
        params_file="./data/params.toml",
        root_folder="/media/benyishay_la/Data/Experiments/",
    )
