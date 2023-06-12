import logging
import multiprocessing as mp
import os
import pathlib
import shutil
import signal
import time

import git
import serial
import toml

from flydra_proxy import flydra_proxy
from highspeed_cameras import highspeed_camera
from opto_trigger import opto_trigger
from position_trigger import position_trigger
from stimuli import stimuli


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


def BraidTrigger(
    params_file: str = "./params.toml",
    root_folder: str = "/media/benyishay_la/Data/Experiments/",
):
    # a signal handler to kill the process
    def signal_handler(signum, frame):
        print("Killing all processes...")
        kill_event.set()

    signal.signal(signal.SIGINT, signal_handler)

    # load the params
    params = toml.load(params_file)

    # check if the braid folder exists
    folder = check_braid_folder(root_folder)
    params["folder"] = folder

    # copy the params file and commit info to the braid folder
    shutil.copyfile(params_file, folder + "/params.toml")
    with open(f"{folder}/commit.toml", "w") as f:
        f.write(
            f"commit = {git.Repo(search_parent_directories=True).head.commit.hexsha}"
        )

    # create a manager for the shared variables
    manager = mp.Manager()
    queue = manager.Queue()
    mp_dict = manager.dict()
    kill_event = manager.Event()
    trigger_event = manager.Event()

    # create a barrier to sync processes
    if params["highspeed"]["active"]:
        n_barriers = 5 + len(params["highspeed"]["cameras"])
    barrier = manager.Barrier(n_barriers)
    trigger_barrier = manager.Barrier(n_barriers - 2)

    # create a dictionary to hold all processes
    process_dict = {}

    # start flydra proxy process
    flydra2_url = "http://0.0.0.0:8397/"
    process_dict["flydra_proxy"] = mp.Process(
        target=flydra_proxy,
        args=(flydra2_url, queue, kill_event, barrier),
        name="flydra_proxy",
    ).start()

    # start position trigger process
    process_dict["position_trigger"] = mp.Process(
        target=position_trigger,
        args=(
            queue,
            trigger_event,
            kill_event,
            mp_dict,
            barrier,
            trigger_barrier,
            params,
        ),
        name="position_trigger",
    ).start()

    # start opto trigger process
    process_dict["opto_trigger"] = mp.Process(
        target=opto_trigger,
        args=(trigger_event, kill_event, mp_dict, barrier, trigger_barrier, params),
        name="opto_trigger",
    ).start()

    # start stimuli process
    process_dict["stimuli"] = mp.Process(
        target=stimuli,
        args=(trigger_event, kill_event, mp_dict, barrier, trigger_barrier, params),
        name="stimuli",
    ).start()

    # if highspeed cameras are active, start them
    if params["highspeed"]["active"]:
        # connect to highspeed trigger
        highspeed_board = serial.Serial(
            params["arduino_devices"]["camera_trigger"], 9600
        )

        # setup video save folder
        save_folder = os.path.basename(params["folder"])[:-6]
        if not os.path.exists(f"/home/benyishay_la/Videos/{save_folder}"):
            os.mkdir(f"/home/benyishay_la/Videos/{save_folder}")

        # initialize all camera processes
        camera_processes = []
        for _, camera_serial in params["highspeed"]["cameras"].items():
            camera_processes.append(
                mp.Process(
                    target=highspeed_camera,
                    args=(
                        camera_serial,
                        save_folder,
                        trigger_event,
                        kill_event,
                        mp_dict,
                        barrier,
                        trigger_barrier,
                        params,
                    ),
                    name=f"highspeed_camera_{camera_serial}",
                ).start()
            )
            time.sleep(3)

    logging.info("Reached barrier")
    # wait until all processes finish intializing
    barrier.wait()

    # start camera trigger
    if params["highspeed"]["active"]:
        highspeed_board.write(b"H")

    logging.info("All proceeses initialized...")
    # start main loop
    while True:
        if kill_event.is_set():
            break

    # stop camera trigger
    if params["highspeed"]["active"]:
        highspeed_board.write(b"L")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(processName)s: %(asctime)s - %(message)s"
    )
    BraidTrigger(
        params_file="./params.toml", root_folder="/media/benyishay_la/Data/Experiments/"
    )
