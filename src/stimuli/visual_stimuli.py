import os
import random
import time
from abc import ABC, abstractmethod
import numpy as np
import pygame
import logging
import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(name="VisualStimuli")

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


class StaticImageStimulus(Stimulus):
    def __init__(self, config):
        super().__init__(config)
        self.surface = self._create_surface(config)

    def _create_surface(self, config):
        if config["image"] == "random":
            return self._generate_random_stimuli()
        else:
            return self._load_image(config["image"])

    def _load_image(self, image_path):
        return pygame.image.load(image_path).convert()

    def _generate_random_stimuli(
        self, width: int = 640, height: int = 128, ratio: int = 8
    ):
        if width % ratio != 0 or height % ratio != 0:
            raise ValueError("width and height must be divisible by ratio")

        stimulus = (
            np.random.choice([0, 1], size=(int(width / ratio), int(height / ratio)))
            * 255
        )

        surface = pygame.surfarray.make_surface(stimulus)

        return pygame.transform.scale(surface, (width, height))

    def update(self, screen, time_elapsed):
        screen.blit(self.surface, (0, 0))


# Helper function for wrap-around
def wrap_around_position(x, screen_width):
    """
    Returns the wrap-around position of a given value `x` within a given `screen_width`.

    Args:
        x (int): The value to wrap around.
        screen_width (int): The width of the screen.

    Returns:
        int: The wrap-around position of `x` within `screen_width`.
    """
    return x % screen_width


def interp_angle(angle):
    """
    Interpolates the given angle using the calibration data from the CSV file.

    Parameters:
        angle (float): The angle to interpolate.

    Returns:
        float: The interpolated value.

    Raises:
        FileNotFoundError: If the CSV file is not found.

    """
    df = pd.read_csv("src/stimuli/calibration.csv")
    screen = df["circle"].values
    heading = df["angle"].values

    return np.interp(angle, heading, screen, period=2 * np.pi)


# Looming stimulus
class LoomingStimulus(Stimulus):
    def __init__(self, config):
        """
        Initializes a LoomingStimulus object.

        Args:
            config (dict): A dictionary containing the configuration parameters for the stimulus.
                - end_radius (int): The maximum radius of the looming stimulus. Defaults to 0.
                - duration (int): The duration of the looming stimulus in milliseconds. Defaults to 150.
                - position_type (str): The type of position for the looming stimulus. Possible values are "random", "closed-loop", or a specific position.
                - expansion_type (str, optional): The type of expansion for the looming stimulus. Possible values are "exponential" or "natural". Defaults to "exponential".

        Returns:
            None
        """
        super().__init__(config)
        self.max_radius = self._get_value(config["end_radius"], 0, 100)
        self.duration = self._get_value(config["duration"], 150, 500)
        self.color = pygame.Color("black")
        self.position_type = config["position_type"]
        self.position = None
        self.start_time = None
        self.expanding = False
        self.type = config.get("expansion_type", "exponential")

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
        self.max_radius = self._get_value(self.config["end_radius"], 32, 64)
        self.duration = self._get_value(self.config["duration"], 150, 500)

        if self.position_type == "random":
            self.position = self._get_value("random", 0, SCREEN_WIDTH)

        elif self.position_type == "closed-loop":
            if heading_direction is not None:
                self.position = int(interp_angle(heading_direction))
                logger.debug(
                    f"heading_direction: {heading_direction}, position: {self.position}"
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
