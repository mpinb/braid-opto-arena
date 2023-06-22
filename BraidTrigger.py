import logging
import multiprocessing as mp
import os
import pathlib
import shutil
import time
import tomllib

import git
import serial

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
    # load the params
    with open(params_file, "rb") as pf:
        params = tomllib.load(pf)

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
    queue = (
        manager.Queue()
    )  # main queue to pass messages between braid proxy and position trigger
    mp_dict = (
        manager.dict()
    )  # a shared dict that gets updated with positional and debug information on trigger
    kill_event = manager.Event()  # the main event to kill all processes
    trigger_event = manager.Event()  # the main event to trigger the processes

    # count number of barriers
    n_barriers = 3  # for main process, flydra_proxy, and position_trigger

    if params["opto_params"]["active"]:  # opto trigger
        n_barriers += 1

    if params["highspeed"]["active"]:  # highspeed camera(s)
        n_barriers += len(params["highspeed"]["cameras"])

    # check if the static stimulus is active
    # if so, we don't actually need to add a barrier object, since it's static
    stim_active = False
    if params["stim_params"]["static"]["active"]:
        stim_active = True

    # but also check if any of the dynamic stimuli are active, cause then we need a barrier
    if (
        params["stim_params"]["grating"]["active"]
        or params["stim_params"]["looming"]["active"]
    ):
        n_barriers += 1
        stim_active = True

    # initialize barrier
    barrier = manager.Barrier(n_barriers)

    n_processes = n_barriers - 2  # ignoring the main process and the flydra proxy

    lock = mp.Lock()
    got_trigger_counter = mp.Value("i", 0)

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
            got_trigger_counter,
            lock,
            n_processes,
            params,
        ),
        name="position_trigger",
    ).start()

    if params["opto_params"]["active"]:
        # start opto trigger process
        process_dict["opto_trigger"] = mp.Process(
            target=opto_trigger,
            args=(
                trigger_event,
                kill_event,
                mp_dict,
                barrier,
                got_trigger_counter,
                lock,
                params,
            ),
            name="opto_trigger",
        ).start()

    if stim_active:
        # start stimuli process
        process_dict["stimuli"] = mp.Process(
            target=stimuli,
            args=(
                trigger_event,
                kill_event,
                mp_dict,
                barrier,
                got_trigger_counter,
                lock,
                params,
            ),
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
                        got_trigger_counter,
                        lock,
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
    try:
        while True:
            continue
    except KeyboardInterrupt:
        kill_event.set()

    # stop camera trigger
    if params["highspeed"]["active"]:
        highspeed_board.write(b"L")
        highspeed_board.close()

    # wait for all processes to finish
    for _, process in process_dict.items():
        process.join()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(processName)s: %(asctime)s - %(message)s"
    )
    BraidTrigger(
        params_file="./params.toml", root_folder="/media/benyishay_la/Data/Experiments/"
    )
