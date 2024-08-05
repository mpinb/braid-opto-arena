import argparse
import logging
import time
import os
import re
import yaml
import contextlib

from src.braid_proxy import connect_to_braid_proxy, parse_chunk
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
logger = logging.getLogger(__name__)


def wait_for_braid_folder(base_folder):
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
    # Load config
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    # Wait for .braid folder to be created
    braid_folder = wait_for_braid_folder(base_folder=config["experiment"]["base_path"])

    # Connect to braid
    braid_proxy = connect_to_braid_proxy(braid_url=config["braid"]["url"])

    # Start processes
    sub_processes = {}
    if config["visual_stimuli"]["enabled"]:
        sub_processes["visual_stimuli"] = start_visual_stimuli_process(
            args.config, braid_folder
        )
    if config["ximea_camera"]["enabled"]:
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
        power_supply = stack.enter_context(PowerSupply(config["hardware"]["backlight"]))
        power_supply.set_voltage(config["hardware"]["backlight"]["voltage"])

        # Set up CsvWriter
        csv_writer = stack.enter_context(
            CsvWriter(filename=os.path.join(braid_folder, "opto.csv"))
        )

        # Set up OptoTrigger if enabled
        if config["optogenetic_light"]["enabled"]:
            opto_trigger = stack.enter_context(OptoTrigger(config))
        else:
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

        # Main loop
        for chunk in braid_proxy.iter_content(chunk_size=None, decode_unicode=True):
            data = parse_chunk(chunk)
            try:
                msg_dict = data["msg"]
            except KeyError:
                continue

            if "Birth" in msg_dict:
                trigger_handler.handle_birth(msg_dict["obj_id"])
            elif "Update" in msg_dict:
                trigger_handler.handle_update(msg_dict)
            elif "Death" in msg_dict:
                trigger_handler.handle_death(msg_dict["obj_id"])
            else:
                logger.debug(f"Got unknown message: {msg_dict}")

    logger.info("Main loop completed. All resources have been closed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", default="config.yaml", help="Path to the configuration file"
    )
    args = parser.parse_args()

    main(args)
