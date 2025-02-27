# ./src/stimuli/visual_controller.py
import argparse
import json
import os

# Disable debugger warning about frozen modules
os.environ["PYDEVD_DISABLE_FILE_VALIDATION"] = "1"

# Hide Pygame support prompt (which includes the AVX2 warning)
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"

import logging  # noqa: E402
import sys  # noqa: E402

import pygame  # noqa: E402
import yaml  # noqa: E402
import zmq  # noqa: E402

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from csv_writer import CsvWriter  # noqa: E402
from messages import Subscriber  # noqa: E402
from visual_stimuli import (  # noqa: E402
    GratingStimulus,
    LoomingStimulus,
    StaticImageStimulus,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(name="VisualController")

SCREEN_WIDTH = 640
SCREEN_HEIGHT = 128

STIMULUS_TYPES = {
    "static": StaticImageStimulus,
    "looming": LoomingStimulus,
    "grating": GratingStimulus,
}


def create_stimuli(config: dict):
    """
    Create a list of stimuli based on the given configuration.

    Args:
        config (dict): The configuration dictionary containing the stimuli information.

    Returns:
        list: A list of stimuli objects.

    This function iterates over the "stimuli" key in the given configuration dictionary.
    For each stimulus, it checks if it is enabled. If it is enabled, it retrieves the
    corresponding stimulus class from the STIMULUS_TYPES dictionary based on the "type"
    key of the stimulus. If a stimulus class is found, it creates an instance of the stimulus
    class using the stimulus dictionary and adds it to the list of stimuli. If no stimulus
    class is found, it prints a warning message indicating an unknown stimulus type.

    The function returns the list of stimuli objects.
    """
    stimuli = []
    for stim in config["stimuli"]:
        if stim["enabled"]:
            stimulus_class = STIMULUS_TYPES.get(stim["type"])
            if stimulus_class:
                stimuli.append(stimulus_class(stim))
            else:
                print(f"Warning: Unknown stimulus type '{stim['type']}'")

    return stimuli


def process_zmq_messages(subscriber, stimuli, csv_writer):
    """
    Process ZMQ messages received by the subscriber.

    Args:
        subscriber (zmq.Socket): The ZMQ subscriber socket.
        stimuli (list): A list of stimulus objects.
        csv_writer (CSVWriter): The CSV writer object.

    Returns:
        None

    Raises:
        KeyboardInterrupt: If a kill message is received.
        zmq.ZMQError: If there is a ZMQ error.
        json.JSONDecodeError: If there is a JSON decode error.
    """
    try:
        # Use non-blocking receive
        topic, message = subscriber.receive(blocking=False)
        if message is None:
            # No message available, just return
            return

        logger.debug(f"Got message from subscriber: {message}")

        if message == "kill":
            logger.info("Received kill message. Exiting...")
            raise KeyboardInterrupt

        trigger_info = json.loads(message)
        heading_direction = trigger_info.get("heading")
        logger.debug(f"Got heading direction: {heading_direction}")

        for stim in stimuli:
            if isinstance(stim, LoomingStimulus):
                logger.info("Triggering looming stimulus")
                stim.start_expansion(heading_direction)
                updated_info = stim.get_trigger_info()
                trigger_info.update(updated_info)
                csv_writer.write_row(trigger_info)
                logging.info(f"Updated info: {trigger_info}")

    except zmq.ZMQError as e:
        logger.error(f"ZMQ Error: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON Decode Error: {e}")


def cleanup(standalone, csv_writer, subscriber):
    """
    Cleans up resources based on the standalone flag.

    Args:
        standalone (bool): Flag indicating if the cleanup is standalone.
        csv_writer (CSVWriter): The CSV writer object.
        subscriber (zmq.Socket): The ZMQ subscriber socket.

    Returns:
        None
    """
    if not standalone:
        csv_writer.close()
        subscriber.close()

    logger.debug("pygame.display.quit()")
    pygame.display.quit()
    logger.debug("pygame.quit()")
    pygame.quit()


def main(config_file: str, braid_folder: str, standalone: bool):
    """
    Runs the main loop of the stimulus display program.

    Args:
        config_file (str): The path to the configuration file.
        braid_folder (str): The base directory to save the stim.csv file.
        standalone (bool): Whether to run the program in standalone mode without ZMQ.

    Returns:
        None

    Raises:
        KeyboardInterrupt: If the program is interrupted by the user.

    This function initializes Pygame, loads the configuration file, creates the stimuli,
    and enters the main loop. In the main loop, it updates the stimuli, fills the screen,
    and flips the display. If not in standalone mode, it also processes ZMQ messages and
    writes to the stim.csv file. The main loop runs at 60 frames per second. If the program
    is interrupted by the user, it logs a message and exits gracefully.
    """
    # Initialize Pygame
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.NOFRAME)
    pygame.display.set_caption("Stimulus Display")

    # Load config
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    # Create stimuli
    stimuli = create_stimuli(config["visual_stimuli"])

    csv_writer = None
    subscriber = None

    if not standalone:
        csv_writer = CsvWriter(os.path.join(braid_folder, "stim.csv"))
        subscriber = Subscriber(
            address="127.0.0.1", port=config["zmq"]["port"], topics="trigger"
        )
        subscriber.initialize()

    clock = pygame.time.Clock()
    logger.info("Starting main loop")

    try:
        while True:
            time_elapsed = clock.get_time()

            if not standalone:
                process_zmq_messages(subscriber, stimuli, csv_writer)

            screen.fill((255, 255, 255))
            for stim in stimuli:
                stim.update(screen, time_elapsed)

            pygame.display.flip()
            clock.tick(60)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Exiting...")
    finally:
        if not standalone:
            cleanup(standalone, csv_writer, subscriber)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stimulus Display Program")
    parser.add_argument(
        "--config_file",
        default="/home/buchsbaum/src/braid-opto-arena/config.yaml",
        type=str,
        help="Path to the configuration file (.yaml)",
    )
    parser.add_argument(
        "--braid_folder",
        type=str,
        required=False,
        default="",
        help="Base directory to save stim.csv",
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        default=False,
        help="Run the program in standalone mode without ZMQ",
    )
    args = parser.parse_args()

    main(args.config_file, args.braid_folder, args.standalone)
