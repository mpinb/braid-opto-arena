import argparse
import json
import os
import pygame
import toml
import zmq
import logging

from src.csv_writer import CsvWriter
from src.messages import Subscriber
from src.stimuli.visual_stimuli import (
    StaticImageStimulus,
    LoomingStimulus,
    GratingStimulus,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCREEN_WIDTH = 640
SCREEN_HEIGHT = 128


def connect_to_zmq(port: int = 5556):
    subscriber = Subscriber()

    subscriber.subscribe("trigger")
    logger.debug("Subscribed to `trigger` messages")
    return subscriber


def create_stimuli(config):
    stim_config = config["stim_params"]
    stimuli = []
    stimulus_classes = {
        "static": StaticImageStimulus,
        "looming": LoomingStimulus,
        "grating": GratingStimulus,
    }

    for stim_type, StimulusClass in stimulus_classes.items():
        if stim_config[stim_type].get("active", False):
            stimuli.append(StimulusClass(stim_config[stim_type]))

    return stimuli


def main(config_file, base_dir, standalone):
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.NOFRAME)
    pygame.display.set_caption("Stimulus Display")

    with open(config_file, "r") as f:
        config = toml.load(f)

    stimuli = create_stimuli(config)

    if not standalone:
        csv_writer = CsvWriter(os.path.join(base_dir, "stim.csv"))
        subscriber = connect_to_zmq()

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
                try:
                    topic, message = subscriber.receive()
                    logger.debug(f"Got message from subscriber: {message}")

                    if message == "kill":
                        logger.info("Received kill message. Exiting...")
                        raise SystemExit

                    elif message:
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

            screen.fill((255, 255, 255))
            for stim in stimuli:
                stim.update(screen, time_elapsed)

            pygame.display.flip()
            clock.tick(60)

    except SystemExit:
        logger.info("Exiting...")
    finally:
        if not standalone:
            csv_writer.close()
            subscriber.close()

        logger.debug("pygame.display.quit()")
        pygame.display.quit()
        logger.debug("pygame.quit()")
        pygame.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stimulus Display Program")
    parser.add_argument(
        "config_file", type=str, help="Path to the configuration file (.toml)"
    )
    parser.add_argument(
        "--base_dir",
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

    main(args.config_file, args.base_dir, args.standalone)
