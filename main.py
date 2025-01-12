"""
Main script for running the experimental setup.
Coordinates all processes and handles the main experimental loop.
"""

import argparse
import contextlib
import logging
import os
import re
import time
from typing import Optional

# Use package-level imports
from src.core import BraidProxy, ConfigManager, CsvWriter, Publisher
from src.devices import OptoTrigger, PowerSupply
from src.handlers import TriggerHandler
from src.process import (
    DisplayControllerConfig,
    DisplayProcess,
    LensControllerConfig,
    LensControllerProcess,
    ProcessGroup,
    XimeaCameraProcess,
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.DEBUG
)
logger = logging.getLogger(name="Main")


def wait_for_braid_folder(base_folder: str) -> str:
    """
    Waits for a new folder with a name matching the pattern 'number_number.braid'.

    Args:
        base_folder: Base directory to monitor

    Returns:
        str: Full path to the found .braid folder
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


def setup_processes(config: ConfigManager, braid_folder: str) -> ProcessGroup:
    """
    Set up all required processes based on configuration.

    Args:
        config: Configuration manager
        braid_folder: Path to the braid data folder

    Returns:
        ProcessGroup: Group of initialized processes
    """
    processes = ProcessGroup()

    # Create videos folder
    videos_folder = os.path.join(
        config.get("experiment", "video_base_path"), os.path.basename(braid_folder)
    ).split(".")[0]
    logger.info(f"Saving videos to {videos_folder}")
    os.makedirs(videos_folder, exist_ok=True)

    # Initialize visual stimuli process if enabled
    if config.get("visual_stimuli", "enabled"):
        display_config = DisplayControllerConfig(
            config_path=config.get("visual_stimuli", "config_file"),
            braid_folder=braid_folder,
        )
        processes.add_process("visual_stimuli", DisplayProcess(display_config))

    # Initialize camera and lens processes if enabled
    if config.get("high_speed_camera", "enabled"):
        # Camera process
        processes.add_process("ximea_camera", XimeaCameraProcess(videos_folder))

        # Lens controller process
        lens_config = LensControllerConfig(
            braid_url=f"{config.get('braid', 'url')}:{config.get('braid', 'event_port')}/",
            lens_port=config.get("hardware", "lensdriver", "port"),
            config_file=config.get("lens_controller", "config_file"),
            interp_file=config.get("lens_controller", "interp_file"),
            video_folder_path=videos_folder,
        )
        processes.add_process("liquid_lens", LensControllerProcess(lens_config))

    return processes


def setup_braid_proxy(config: ConfigManager) -> BraidProxy:
    """Set up and initialize BraidProxy."""
    return BraidProxy(
        base_url=config.get("braid", "url"),
        event_port=config.get("braid", "event_port"),
        control_port=config.get("braid", "control_port"),
    )


def main(args: argparse.Namespace) -> None:
    """
    Main function running the experimental setup.

    Args:
        args: Command line arguments
    """
    # Initialize configuration
    config = ConfigManager(args.config)

    # Calculate time limit if specified
    time_limit_hours = config.get("experiment", "time_limit")
    time_limit_seconds = time_limit_hours * 3600 if time_limit_hours else None

    # Initialize BraidProxy
    braid_proxy = setup_braid_proxy(config)

    # Start recording and wait for braid folder
    braid_proxy.toggle_recording(start=True)
    braid_folder = wait_for_braid_folder(config.get("experiment", "exp_base_path"))

    # Set up processes
    processes = setup_processes(config, braid_folder)

    # Set up resources using context managers
    with contextlib.ExitStack() as stack:
        # Start all processes
        stack.enter_context(processes)

        # Set up PowerSupply
        power_supply = stack.enter_context(
            PowerSupply(config.get("hardware", "backlight", "port"))
        )
        power_supply.set_voltage(config.get("hardware", "backlight", "voltage"))

        # Set up OptoTrigger and CSV if enabled
        opto_trigger = None
        csv_writer = None
        if config.get("optogenetic_light", "enabled"):
            csv_writer = stack.enter_context(
                CsvWriter(filename=os.path.join(braid_folder, "opto.csv"))
            )
            opto_trigger = stack.enter_context(OptoTrigger(config))

        # Set up Publisher and TriggerHandler
        trigger_publisher = stack.enter_context(Publisher(config.get("zmq", "port")))
        trigger_handler = stack.enter_context(
            TriggerHandler(
                config.get("trigger"), opto_trigger, csv_writer, trigger_publisher
            )
        )

        logger.info("All resources initialized. Starting main loop.")
        if time_limit_hours:
            logger.info(f"Time limit set to {time_limit_hours} hours.")

        run_main_loop(
            braid_proxy=braid_proxy,
            processes=processes,
            trigger_handler=trigger_handler,
            start_time=time.time(),
            time_limit_seconds=time_limit_seconds,
        )

    logger.info("Main loop completed. All resources have been closed.")


def run_main_loop(
    braid_proxy: BraidProxy,
    processes: ProcessGroup,
    trigger_handler: TriggerHandler,
    start_time: float,
    time_limit_seconds: Optional[float],
) -> None:
    """Run the main experimental loop."""
    shutdown_requested = False
    
    try:
        for event in braid_proxy.iter_events():
            if shutdown_requested:
                break
                
            # Check process health
            if not processes.check_all_alive():
                logger.error("One or more processes died unexpectedly")
                shutdown_requested = True
                break

            # Check time limit
            if time_limit_seconds and (time.time() - start_time > time_limit_seconds):
                logger.info("Time limit reached. Shutting down gracefully...")
                shutdown_requested = True
                break

            if event is None:
                continue

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
        shutdown_requested = True
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        shutdown_requested = True
    finally:
        # Explicit shutdown sequence
        try:
            logger.info("Starting shutdown sequence...")
            
            # First stop recording
            logger.info("Stopping Braid recording...")
            braid_proxy.toggle_recording(start=False)
            
            # Then stop all processes in reverse order
            logger.info("Stopping all processes...")
            processes.stop_all()
            
            logger.info("Shutdown sequence completed successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            # In case of shutdown error, try to force stop processes
            try:
                processes.stop_all()
            except:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experimental Control Script")
    parser.add_argument(
        "--config", default="config.yaml", help="Path to the configuration file"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Run without active Braid tracking"
    )
    args = parser.parse_args()

    main(args)
