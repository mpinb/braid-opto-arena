import multiprocessing as mp
import logging
import signal
import tomllib
import shutil
import pathlib
import time
import git
import serial

from highspeed_cameras import start_highspeed_cameras
from flydra_proxy import flydra_proxy
from position_trigger import position_trigger
from stimuli import stimuli
from opto_trigger import opto_trigger


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
    queue = manager.Queue()
    mp_dict = manager.dict()
    kill_event = manager.Event()
    trigger_event = manager.Event()

    # create a barrier to sync processes
    if params["highspeed_cameras"]["active"]:
        n_barriers = 5 + len(params["highspeed"]["cameras"])
    barrier = manager.Barrier(n_barriers)

    # create a dictionary to hold all processes
    process_dict = {}

    # start flydra proxy process
    process_dict["flydra_proxy"] = mp.Process(
        target=flydra_proxy, args=(params["flydra2_url"], queue, kill_event, barrier)
    ).start()

    # start position trigger process
    process_dict["position_trigger"] = mp.Process(
        target=position_trigger,
        args=(queue, trigger_event, kill_event, mp_dict, barrier, params),
    ).start()

    # start opto trigger process
    process_dict["opto_trigger"] = mp.Process(
        target=opto_trigger, args=(trigger_event, kill_event, mp_dict, barrier, params)
    ).start()

    # start stimuli process
    process_dict["stimuli"] = mp.Process(
        target=stimuli, args=(trigger_event, kill_event, mp_dict, barrier, params)
    ).start()

    # if highspeed cameras are active, start them
    if params["highspeed_cameras"]["active"]:
        # connect to highspeed trigger
        highspeed_board = serial.Serial(
            params["arduino_devices"]["camera_trigger"], 9600
        )

        # start highspeed camera processes
        highspeed_cameras = start_highspeed_cameras(
            trigger_event,
            kill_event,
            mp_dict,
            barrier,
            params,
        )

    # wait until all processes finish intializing
    barrier.wait()

    # start camera trigger
    if params["highspeed_cameras"]["active"]:
        highspeed_board.write(b"H")

    # start main loop
    while True:
        if kill_event.is_set():
            break

    # stop camera trigger
    if params["highspeed_cameras"]["active"]:
        highspeed_board.write(b"L")

    # join all processes
    [p.join() for p in highspeed_cameras]
    [p.join() for p in process_dict.values()]


if __name__ == "__main__":
    logging.basicConfig(level=logging.info, format="%(asctime)s - %(message)s")
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    BraidTrigger(
        params_file="./params.toml", root_folder="/media/benyishay_la/Data/Experiments/"
    )
