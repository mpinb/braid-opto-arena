import argparse
import logging
import time
import os
import re
import yaml
import contextlib

from src.braid_proxy import BraidProxy
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

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(name="Main")


def wait_for_braid_folder(base_folder):
    """
    Waits for a new folder with a name matching the pattern 'number_number.braid' in the given base folder.
    """
    pattern = r"\d+_\d+\.braid"
    logger.info(f"Monitoring {base_folder} for new .braid folders...")
    while True:
        for item in os.listdir(base_folder):
            full_path = os.path.join(base_folder, item)
            if os.path.isdir(full_path) and re.match(pattern, item):
                logger.info(f"Found matching folder: {full_path}")
                return full_path
        time.sleep(1)


def main(args):
    # Load config
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    time_limit_hours = config.get("experiment", {}).get(
        "time_limit", None
    )  # Default to None hours if not specified
    time_limit_seconds = (
        time_limit_hours * 3600 if time_limit_hours is not None else None
    )

    # Initialize BraidProxy
    braid_proxy = BraidProxy(
        base_url=config["braid"]["url"],
        event_port=config["braid"]["event_port"],
        control_port=config["braid"]["control_port"],
    )

    # Start recording
    braid_proxy.toggle_recording(start=True)

    # Wait for .braid folder to be created
    braid_folder = wait_for_braid_folder(
        base_folder=config["experiment"]["exp_base_path"]
    )

    # Start processes
    sub_processes = {}
    if config["visual_stimuli"]["enabled"]:
        sub_processes["visual_stimuli"] = start_visual_stimuli_process(
            args.config, braid_folder
        )

    # set and create videos folder
    videos_folder = os.path.join(
        config["experiment"]["video_base_path"], os.path.basename(braid_folder)
    ).split(".")[0]
    logging.info(f"Saving videos to {videos_folder}")
    os.makedirs(videos_folder, exist_ok=True)

    if config["high_speed_camera"]["enabled"]:
        sub_processes["ximea_camera"] = start_ximea_camera_process(videos_folder)
        sub_processes["liquid_lens"] = start_liquid_lens_process(
            braid_url=f"{config['braid']['url']}:{config['braid']['event_port']}/",
            lens_port=config["hardware"]["lensdriver"]["port"],
            video_folder_path=videos_folder,
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

        logger.info("All resources initialized. Starting main loop.")
        if time_limit_hours is not None:
            logger.info(f"Time limit set to {time_limit_hours} hours.")

        # Main loop
        start_time = time.time()
        try:
            for event in braid_proxy.iter_events():
                # Check for time limit
                if (time_limit_seconds is not None) and (
                    time.time() - start_time > time_limit_seconds
                ):
                    logger.info("Time limit reached. Shutting down gracefully...")
                    break

                # continue the loop if event is None
                if event is None:
                    continue

                # handle event otherwise
                else:
                    msg_dict = event.get("msg", {})
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
        finally:
            braid_proxy.toggle_recording(start=False)

    logger.info("Main loop completed. All resources have been closed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", default="config.yaml", help="Path to the configuration file"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Run without active Braid tracking"
    )
    args = parser.parse_args()

    main(args)
