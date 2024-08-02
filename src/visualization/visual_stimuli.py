import argparse
import json
import os
import random
import time
from abc import ABC, abstractmethod
import numpy as np
import pygame
import toml
import zmq
from utils.csv_writer import CsvWriter
from utils.log_config import setup_logging
from core.messages import Subscriber

logger = setup_logging(logger_name="VisualStimuli", level="INFO", color="yellow")

# Constants
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 128
os.environ["SDL_VIDEO_WINDOW_POS"] = "%d,%d" % (0, 0)


# Base stimulus class
class Stimulus(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def update(self, screen, time_elapsed):
        pass


# Static image stimulus
class StaticImageStimulus(Stimulus):
    def __init__(self, config):
        super().__init__(config)
        self.image = pygame.image.load(config["image"]).convert()
        self.image = pygame.transform.scale(self.image, (SCREEN_WIDTH, SCREEN_HEIGHT))

    def update(self, screen, time_elapsed):
        screen.blit(self.image, (0, 0))


# Helper function for wrap-around
def wrap_around_position(x, screen_width):
    return x % screen_width


def interp_angle(angle):
    screen = [0, 128, 256, 384, 512]
    heading = [1.518, 2.776, -2.198, -0.978, 0.213]

    return np.interp(angle, heading, screen, period=2 * np.pi)


# Looming stimulus
class LoomingStimulus(Stimulus):
    def __init__(self, config):
        super().__init__(config)
        self.max_radius = self._get_value(config["max_radius"], 0, 100)
        self.duration = self._get_value(config["duration"], 150, 500)
        self.color = pygame.Color(config["color"])
        self.position_type = config["position"]
        self.position = None
        self.start_time = None
        self.expanding = False
        self.type = config["stim_type"]

    def _get_value(self, value, min_val, max_val):
        if value == "random":
            return random.randint(min_val, max_val)
        return value

    def generate_natural_looming(
        self, max_radius, duration, l_v=10, distance_from_screen=25, hz=60
    ):
        n_frames = int(duration / (1000 / hz))
        r = np.flip([2 * np.arctan(l_v / i) for i in range(1, n_frames)])
        looming_size_on_screen = np.tan(r / 2) * distance_from_screen
        looming_size_on_screen = (
            looming_size_on_screen - np.min(looming_size_on_screen)
        ) / (np.max(looming_size_on_screen) - np.min(looming_size_on_screen))
        looming_size_on_screen = looming_size_on_screen * max_radius
        return looming_size_on_screen

    def generate_exponential_looming(self, max_radius, duration, hz=60):
        n_frames = int(duration / (1000 / hz))
        radii_array = np.logspace(0, np.log10(max_radius), n_frames)
        return radii_array

    def start_expansion(self, heading_direction=None):
        self.max_radius = self._get_value(self.config["max_radius"], 32, 64)
        self.duration = self._get_value(self.config["duration"], 150, 500)
        if self.position_type == "random":
            self.position = self._get_value("random", 0, SCREEN_WIDTH)
        elif self.position_type == "closed-loop":
            if heading_direction is not None:
                self.position = interp_angle(heading_direction)
                logger.debug(
                    f" heading_direction: {heading_direction}, position: {self.position}"
                )
            else:
                self.position = self._get_value("random", 0, SCREEN_WIDTH)
        else:
            self.position = self.position_type
        if self.type == "exponential":
            self.radii_array = self.generate_exponential_looming(
                self.max_radius, self.duration
            )
        elif self.type == "natural":
            self.radii_array = self.generate_natural_looming(
                self.max_radius, self.duration
            )
        self.start_time = time.time()
        self.curr_frame = 0
        self.n_frames = int(self.duration / (1000 / 60))
        self.expanding = True

    def update(self, screen, time_elapsed):
        if self.expanding:
            if self.curr_frame < self.n_frames - 1:
                if self.type == "linear":
                    self.radius = (self.curr_frame / self.n_frames) * self.max_radius
                else:
                    self.radius = self.radii_array[self.curr_frame]

                position = wrap_around_position(self.position, SCREEN_WIDTH)
                pygame.draw.circle(
                    screen, self.color, (position, SCREEN_HEIGHT // 2), int(self.radius)
                )
                if position - self.radius < 0:
                    pygame.draw.circle(
                        screen,
                        self.color,
                        (position + SCREEN_WIDTH, SCREEN_HEIGHT // 2),
                        int(self.radius),
                    )
                if position + self.radius > SCREEN_WIDTH:
                    pygame.draw.circle(
                        screen,
                        self.color,
                        (position - SCREEN_WIDTH, SCREEN_HEIGHT // 2),
                        int(self.radius),
                    )
                self.curr_frame += 1
            else:
                self.expanding = False

    def get_trigger_info(self):
        return {
            "timestamp": time.time(),
            "stimulus": self.type,
            "expansion": self.expanding,
            "max_radius": self.max_radius,
            "duration": self.duration,
            "color": self.color,
            "position": self.position,
        }


# Grating stimulus
class GratingStimulus(Stimulus):
    def __init__(self, config):
        super().__init__(config)
        self.frequency = config["frequency"]
        self.direction = config["direction"]
        self.color = pygame.Color(config["color"])

    def update(self, screen, time_elapsed):
        pass


def connect_to_zmq(pub_port: int = 5556, handshake_port: int = 5557):
    subscriber = Subscriber(pub_port, handshake_port)
    subscriber.handshake()
    logger.debug("Handshake successful")
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
