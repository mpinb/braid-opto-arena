import argparse
import json
import os
import random
import time
from abc import ABC, abstractmethod
import numpy as np
import pygame
import toml
from messages import Subscriber
from utils.csv_writer import CsvWriter
import signal

# from scipy.interpolate import interp1d
import logging

from utils.log_config import setup_logging

setup_logging(level="INFO")
logger = logging.getLogger(__name__)

# Constants
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 128
os.environ["SDL_VIDEO_WINDOW_POS"] = "%d,%d" % (0, 0)


# Function to ignore SIGINT (Ctrl+C)
def ignore_signal(signum, frame):
    print("SIGINT signal ignored")


# Set the handler for SIGINT to the ignore function
signal.signal(signal.SIGINT, ignore_signal)


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
        # get looming duration in frames from ms
        n_frames = int(duration / (1000 / hz))

        # generate the angular looming size
        r = np.flip([2 * np.arctan(l_v / i) for i in range(1, n_frames)])

        # calculate the looming size on screen
        looming_size_on_screen = np.tan(r / 2) * distance_from_screen

        # normalize from 0 to 1
        looming_size_on_screen = (
            looming_size_on_screen - np.min(looming_size_on_screen)
        ) / (np.max(looming_size_on_screen) - np.min(looming_size_on_screen))

        # scale to max_radius
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
                    f"visual_stimuli.py: heading_direction: {heading_direction}, position: {self.position}"
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

        # control stimulus by framerate
        self.curr_frame = 0
        self.n_frames = int(self.duration / (1000 / 60))

        self.expanding = True

    def update(self, screen, time_elapsed):
        if self.expanding:
            # elapsed = (time.time() - self.start_time) * 1000  # convert to milliseconds
            if self.curr_frame < self.n_frames - 1:
                if self.type == "linear":
                    self.radius = (self.curr_frame / self.n_frames) * self.max_radius
                else:
                    self.radius = self.radii_array[self.curr_frame]

                # Draw the circle normally
                position = wrap_around_position(self.position, SCREEN_WIDTH)
                pygame.draw.circle(
                    screen, self.color, (position, SCREEN_HEIGHT // 2), int(self.radius)
                )

                # Check for wrap-around and draw additional circles if necessary
                if position - self.radius < 0:  # Circle extends past the left edge
                    pygame.draw.circle(
                        screen,
                        self.color,
                        (position + SCREEN_WIDTH, SCREEN_HEIGHT // 2),
                        int(self.radius),
                    )
                if (
                    position + self.radius > SCREEN_WIDTH
                ):  # Circle extends past the right edge
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
        # Implementation for grating stimulus
        pass


# Main function
def main(config_path, base_dir_path, standalone):
    # Initialize pygame
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.NOFRAME)
    pygame.display.set_caption("Stimulus Display")

    # Load configuration
    config = toml.load(config_path)

    stim_config = config["stim_params"]

    # Create stimuli
    stimuli = []
    if stim_config["static"].get("active", False):
        stimuli.append(StaticImageStimulus(stim_config["static"]))
    if stim_config["looming"].get("active", False):
        stimuli.append(LoomingStimulus(stim_config["looming"]))
    if stim_config["grating"].get("active", False):
        stimuli.append(GratingStimulus(stim_config["grating"]))

    # CSV logging setup
    if not standalone:
        csv_writer = CsvWriter(os.path.join(base_dir_path, "stim.csv"))

    # ZMQ setup if not standalone
    subscriber = None
    if not standalone:
        subscriber = Subscriber(pub_port=5556, handshake_port=5557)
        subscriber.handshake()
        logger.debug("visual_stimuli.py: Handshake successful")
        subscriber.subscribe("trigger")
        logger.debug("visual_stimuli.py: Subscribed to all messages")

    # Main loop
    clock = pygame.time.Clock()
    logger.info("visual_stimuli.py: Starting main loop")
    while True:
        time_elapsed = clock.get_time()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                # keep_running = False
                break
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_k:
                    logger.info("visual_stimuli.py: Key pressed: K")
                    for stim in stimuli:
                        if isinstance(stim, LoomingStimulus):
                            stim.start_expansion()

        if not standalone:
            _, message = subscriber.receive()
            logger.debug(f"Got message from subscriber: {message}")

            if message == "kill":
                logger.info("visual_stimuli.py: Received kill message. Exiting...")
                break

            elif message is not None:
                trigger_info = json.loads(message)
                heading_direction = trigger_info["heading_direction"]
                logger.info(f"visual_stimuli.py: triggering stimulus {trigger_info}")
                logger.debug(f"Got heading direction: {heading_direction}")

                # Handle trigger for looming stimulus
                for stim in stimuli:
                    if isinstance(stim, LoomingStimulus):
                        stim.start_expansion(heading_direction)
                        updated_info = stim.get_trigger_info()
                        trigger_info.update(updated_info)

                        # Log the event
                        csv_writer.write(trigger_info)
            else:
                pass

        # Update screen
        screen.fill((255, 255, 255))
        for stim in stimuli:
            stim.update(screen, time_elapsed)
        pygame.display.flip()
        clock.tick(60)

    # Clean up
    if not standalone:
        csv_writer.close()

    subscriber.close()
    pygame.display.quit()
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
