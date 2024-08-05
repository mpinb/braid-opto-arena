import os
import random
import time
from abc import ABC, abstractmethod
import numpy as np
import pygame
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        self.surface = self._create_surface(config)

    def _create_surface(self, config):
        if "image" in config:
            return self._load_image(config["image"])
        else:
            return self._generate_random_stimuli(config)

    def _load_image(self, image_path):
        try:
            image = pygame.image.load(image_path).convert()
        except pygame.error as e:
            print(f"Unable to load image: {e}")
            # Return a default surface or raise an exception
        return pygame.transform.scale(
            image,
            (
                self.config.get("width", SCREEN_WIDTH),
                self.config.get("height", SCREEN_HEIGHT),
            ),
        )

    def _generate_random_stimuli(self, config):
        width = config.get("width", SCREEN_WIDTH)
        height = config.get("height", SCREEN_HEIGHT)
        min_size = config.get("min_size", 10)
        stimulus = self.generate_random_stimuli(width, height, min_size)
        return pygame.surfarray.make_surface(stimulus * 255)

    def update(self, screen, time_elapsed):
        screen.blit(self.surface, (0, 0))

    @staticmethod
    def generate_random_stimuli(
        width: int = 640, height: int = 128, min_size: int = 10
    ):
        stimulus = np.zeros((height, width), dtype=np.int8)
        max_squares_x = width // min_size
        max_squares_y = height // min_size
        num_squares = np.random.randint(1, max_squares_x * max_squares_y + 1)

        for _ in range(num_squares):
            x = np.random.randint(0, width - min_size + 1)
            y = np.random.randint(0, height - min_size + 1)
            size_x = np.random.randint(min_size, min(width - x + 1, min_size * 2))
            size_y = np.random.randint(min_size, min(height - y + 1, min_size * 2))
            stimulus[y : y + size_y, x : x + size_x] = 1

        return stimulus


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
        self.max_radius = self._get_value(config["stimuli"], 0, 100)
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
