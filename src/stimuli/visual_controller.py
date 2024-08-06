import argparse
import json
import os
import pygame
import yaml
import zmq
import logging
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from csv_writer import CsvWriter
from messages import Subscriber
from stimuli.visual_stimuli import (
    StaticImageStimulus,
    LoomingStimulus,
    GratingStimulus,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCREEN_WIDTH = 640
SCREEN_HEIGHT = 128

STIMULUS_TYPES = {
    "static": StaticImageStimulus,
    "looming": LoomingStimulus,
    "grating": GratingStimulus,
}


def create_stimuli(config: dict):
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
    try:
        topic, message = subscriber.receive()
        logger.debug(f"Got message from subscriber: {message}")

        if message == "kill":
            logger.info("Received kill message. Exiting...")
            raise KeyboardInterrupt

        if message:
            trigger_info = json.loads(message)
            heading_direction = trigger_info.get("heading_direction")
            logger.info("Triggering stimulus")
            logger.debug(f"Got heading direction: {heading_direction}")

            for stim in stimuli:
                if isinstance(stim, LoomingStimulus):
                    stim.start_expansion(heading_direction)
                    updated_info = stim.get_trigger_info()
                    trigger_info.update(updated_info)
                    csv_writer.write(trigger_info)

    except zmq.Again:
        pass
    except zmq.ZMQError as e:
        logger.error(f"ZMQ Error: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON Decode Error: {e}")


def cleanup(standalone, csv_writer, subscriber):
    if not standalone:
        csv_writer.close()
        subscriber.close()

    logger.debug("pygame.display.quit()")
    pygame.display.quit()
    logger.debug("pygame.quit()")
    pygame.quit()


def main(config_file: str, braid_folder: str, standalone: bool):
    # Initialize Pygame
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.NOFRAME)
    pygame.display.set_caption("Stimulus Display")

    # Load config
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    # Create stimuli
    stimuli = create_stimuli(config["visual_stimuli"])

    if not standalone:
        csv_writer = CsvWriter(os.path.join(braid_folder, "stim.csv"))
        subscriber = Subscriber(
            address="127.0.0.1", port=config["zmq"]["port"], topics="trigger"
        )

    clock = pygame.time.Clock()
    logger.info("Starting main loop")

    try:
        while True:
            time_elapsed = clock.get_time()
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN and event.key == pygame.K_k:
                    logger.info("Key pressed: K")
                    for stim in stimuli:
                        if isinstance(stim, LoomingStimulus):
                            stim.start_expansion()

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
        default="config.yaml",
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
        default=True,
        help="Run the program in standalone mode without ZMQ",
    )
    args = parser.parse_args()

    main(args.config_file, args.braid_folder, args.standalone)
