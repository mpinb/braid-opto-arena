# ./main.py

import argparse
import logging
import time
import os
import re
import yaml
import contextlib
from requests.exceptions import ChunkedEncodingError, ConnectionError

from src.braid_proxy import connect_to_braid_proxy, parse_chunk, toggle_recording
from src.devices.opto_trigger import OptoTrigger
from src.devices.power_supply import PowerSupply
from src.csv_writer import CsvWriter
from src.messages import Publisher
from src.trigger_handler import TriggerHandler
from src.process_manager import (
    start_liquid_lens_process,
    start_visual_stimuli_process,
    start_ximea_camera_process,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(name="Main")


def wait_for_braid_folder(base_folder):
    """
    Waits for a new folder with a name matching the pattern 'number_number.braid' in the given base folder.

    Args:
        base_folder (str): The base folder to monitor for new folders.

    Returns:
        str: The full path of the first matching folder found.

    Raises:
        None

    """
    pattern = r"\d+_\d+\.braid"

    logger.info(f"Monitoring {base_folder} for new .braid folders...")

    while True:
        for item in os.listdir(base_folder):
            full_path = os.path.join(base_folder, item)
            if os.path.isdir(full_path) and re.match(pattern, item):
                logger.info(f"Found matching folder: {full_path}")
                return full_path

        time.sleep(1)  # Wait for 1 second before checking again


def main(args):
    """
    The main function that initializes resources, starts processes, and runs the main loop.

    Args:
        args (argparse.Namespace): The command-line arguments.

    Returns:
        None

    Raises:
        KeyboardInterrupt: If the user interrupts the program with a keyboard interrupt.
        Exception: If an unexpected error occurs during the main loop.

    Description:
        This function loads the configuration from a YAML file, waits for a .braid folder to be created,
        connects to the Braid proxy, starts the necessary processes, sets up resources such as the
        PowerSupply, CsvWriter, OptoTrigger (if enabled), Publisher, and TriggerHandler. It then enters
        a main loop that iterates over the Braid proxy's content, parses each chunk, and handles the
        different types of messages received (Birth, Update, Death). If a KeyboardInterrupt is received,
        the program gracefully shuts down. If an unexpected error occurs, it is logged and the program
        continues.

    """
    # Load config
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    # get experiment time limit
    time_limit_hours = config.get("experiment", {}).get("time_limit_hours", None)
    time_limit_seconds = time_limit_hours * 3600 if time_limit_hours is not None else None

    # Wait for .braid folder to be created
    braid_folder = wait_for_braid_folder(
        base_folder=config["experiment"]["exp_base_path"]
    )

    # Connect to braid
    braid_proxy = connect_to_braid_proxy(braid_url=config["braid"]["url"])

    # Start processes
    sub_processes = {}
    if config["visual_stimuli"]["enabled"]:
        sub_processes["visual_stimuli"] = start_visual_stimuli_process(
            args.config, braid_folder
        )
    if config["high_speed_camera"]["enabled"]:
        sub_processes["ximea_camera"] = start_ximea_camera_process(
            config["experiment"]["video_base_path"], braid_folder
        )

        sub_processes["liquid_lens"] = start_liquid_lens_process(
            config["braid"]["url"],
            config["hardware"]["lensdriver"]["port"],
            braid_folder,
        )

    # Set up resources
    with contextlib.ExitStack() as stack:
        # Set up PowerSupply
        power_supply = stack.enter_context(
            PowerSupply(config["hardware"]["backlight"]["port"])
        )
        power_supply.set_voltage(config["hardware"]["backlight"]["voltage"])

        # Set up OptoTrigger and csv if enabled
        if config["optogenetic_light"]["enabled"]:
            csv_writer = stack.enter_context(
                CsvWriter(filename=os.path.join(braid_folder, "opto.csv"))
            )
            opto_trigger = stack.enter_context(OptoTrigger(config))
        else:
            csv_writer = None
            opto_trigger = None

        # Set up Publisher
        trigger_publisher = stack.enter_context(Publisher(config["zmq"]["port"]))

        # Set up TriggerHandler
        trigger_handler = stack.enter_context(
            TriggerHandler(
                config["trigger"], opto_trigger, csv_writer, trigger_publisher
            )
        )

        logger.info("All resources initialized. Starting Braid recording loop.")
        if time_limit_seconds is not None:
            logger.info(f"Experiment time limit: {time_limit_hours} seconds")
        
        time.sleep(1)
        toggle_recording(True, "http://127.0.0.1:32935")

        # Set the start time
        start_time = time.time()

        # Main loop
        try:
            while True:
                # Check if time limit has been reached
                if time_limit_seconds is not None and (time.time() - start_time) > time_limit_seconds:
                    logger.info(f"Time limit of {time_limit_hours} hours reached. Stopping recording.")
                    break

                try:
                    # Use a timeout to ensure we can check the time limit regularly
                    chunk = next(braid_proxy.iter_content(chunk_size=None, decode_unicode=True, timeout=1))
                except StopIteration:
                    # No data available, continue to next iteration
                    continue
                except (ChunkedEncodingError, ConnectionError) as e:
                    logger.error(f"Connection error: {e}. Attempting to reconnect...")
                    # Attempt to reconnect
                    braid_proxy = connect_to_braid_proxy(braid_url=config["braid"]["url"])
                    continue

                data = parse_chunk(chunk)
                try:
                    msg_dict = data["msg"]
                except KeyError:
                    continue

                if "Birth" in msg_dict:
                    trigger_handler.handle_birth(msg_dict["Birth"]["obj_id"])
                elif "Update" in msg_dict:
                    trigger_handler.handle_update(msg_dict["Update"])
                elif "Death" in msg_dict:
                    trigger_handler.handle_death(msg_dict["Death"])
                else:
                    logger.debug(f"Got unknown message: {msg_dict}")

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Shutting down gracefully...")
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")

    toggle_recording(False, "http://127.0.0.1:32935")        
    logger.info("Main loop completed. All resources have been closed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", default="config.yaml", help="Path to the configuration file"
    )
    parser.add_argument(
        "--debug", default=False, help="Run without active Braid tracking"
    )
    args = parser.parse_args()

    main(args)
