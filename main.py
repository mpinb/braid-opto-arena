import argparse
import json
import os
import subprocess
import threading
import time

import tomllib

from src.core.braid_proxy import BraidProxy
from src.core.messages import Subscriber
from src.devices.rspowersupply import PowerSupply
from src.processing.data_processor import DataProcessor
from src.utils.file_operations import (
    check_braid_running,
    copy_files_to_folder,
    get_video_output_folder,
)
from src.utils.log_config import setup_logging

# Get the root directory of the project
root_dir = os.path.abspath(os.path.dirname(__file__))
BRAID_FOLDER = None

# Set the PYTHONPATH environment variable
env = os.environ.copy()
env["PYTHONPATH"] = root_dir

VOLTAGE = 23.5

# Setup logger
logger = setup_logging(logger_name="Main", level="INFO")


def start_camera(params, child_processes):
    logger.info("Opening highspeed camera.")
    params["video_save_folder"] = get_video_output_folder(BRAID_FOLDER)
    video_save_folder = params["video_save_folder"]
    child_processes["ximea_camera"] = subprocess.Popen(
        [
            "libs/ximea_camera/target/release/ximea_camera",
            "--save-folder",
            f"{video_save_folder}",
            "--fps",
            "500",
            "--height",
            "2016",
            "--width",
            "2016",
            "--offset-x",
            "1056",
            "--offset-y",
            "170",
        ]
    )

    # start liquid lens process
    child_processes["liquid_lens"] = subprocess.Popen(
        [
            "libs/lens_controller/target/release/lens_controller",
            "--braid-url",
            "http://10.40.80.6:8397/",
            "--lens-driver-port",
            "/dev/optotune_ld",
            "--update-interval-ms",
            "20",
            "--save-folder",
            f"{BRAID_FOLDER}",
        ],
        env=env,
    )
    logger.info("Highspeed camera connected.")
    return params, child_processes


def start_stimuli(params_file, child_processes):
    logger.info("Starting visual stimuli process.")
    child_processes["visual_stimuli"] = subprocess.Popen(
        [
            "python",
            "./modules/visual_stimuli.py",
            f"{params_file}",
            "--base_dir",
            f"{BRAID_FOLDER}",
        ],
        env=env,
    )

    logger.info("Visual stimuli process connected.")
    return child_processes


def start_braid_proxy():
    # Connect to flydra2 proxy
    braid_proxy = threading.Thread(taget=BraidProxy, daemon=True)
    braid_proxy.connect()
    braid_proxy.run()

    # braid sub channel
    braid_sub = Subscriber(port=12345, topic="braid_proxy")
    braid_sub.connect()

    return braid_proxy, braid_sub


def main(params_file: str, root_folder: str, args: argparse.Namespace):
    """Main BraidTrigger function. Starts up all processes and triggers.
    Loop over data incoming from the flydra2 proxy and tests if a trigger should be sent.

    Args:
        params_file (str): a path to the params.toml file
        root_folder (str): the root folder where the experiment folder will be created
    """
    # Load params
    with open(params_file, "rb") as f:
        params = tomllib.load(f)

    # Check if braidz is running (see if folder was created)
    params["folder"] = check_braid_running(root_folder, args.debug)
    BRAID_FOLDER = params["folder"]

    # Copy the params file to the experiment folder
    copy_files_to_folder(BRAID_FOLDER, params_file)

    # Set power supply voltage (for backlighting)
    ps = (  # noqa: F841
        PowerSupply(port="/dev/powersupply").set_output(VOLTAGE)
        if not args.debug
        else None
    )

    # Start braid proxy
    braid_proxy, braid_sub = start_braid_proxy()
    # start processes
    child_processes = {}

    # Connect to cameras
    if params["highspeed"].get("active", False):
        params, child_processes = start_camera(params, child_processes)

    # check if any visual stimuli is active and start the visual stimuli process
    if any(
        [value.get("active", False) for key, value in params["stim_params"].items()]
    ):
        child_processes = start_stimuli(params_file, child_processes)

    # Initialize DataProcessor
    data_processor = DataProcessor(params)  # noqa: F841

    # Start main loop
    logger.info("Starting main loop.")
    start_time = time.time()
    try:
        while True:
            if (time.time() - start_time) >= params["max_runtime"] * 3600:
                break

            _, msg = braid_sub.recv()
            data = json.loads(msg)
            data_processor.process_data(data)

    except Exception as e:
        logger.error(e)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        if ps:
            logger.info("Shutting down backlight")
            ps.set_output(0)
            ps.dev.close()

        logger.info("Shutting data processor.")
        data_processor.close()

        for name, process in child_processes.items():
            logger.info(f"Terminating {name} process.")
            process.terminate()
            try:
                process.wait(
                    timeout=5
                )  # Wait up to 5 seconds for the process to terminate
            except subprocess.TimeoutExpired:
                logger.warning(f"{name} process did not terminate in time, forcing...")
                process.kill()


if __name__ == "__main__":
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", default=False)
    parser.add_argument(
        "--use-zmq",
        action="store_true",
        default=True,
        help="Use ZMQ for data streaming instead of direct yield",
    )
    args = parser.parse_args()

    # Start main function
    logger.info("Starting main function.")
    main(
        params_file="./params.toml",
        root_folder="/home/buchsbaum/mnt/DATA/Experiments/",
        args=args,
    )
