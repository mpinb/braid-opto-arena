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


def generate_qr_like_stimuli(
    width: int = 640, height: int = 640, module_size: int = 10
):
    # Ensure dimensions are multiples of module_size
    width = (width // module_size) * module_size
    height = (height // module_size) * module_size

    # Calculate number of modules in each dimension
    modules_x = width // module_size
    modules_y = height // module_size

    # Initialize the stimulus array with zeros (white background)
    stimulus = np.zeros((height, width), dtype=np.int8)

    # Generate random modules
    for y in range(modules_y):
        for x in range(modules_x):
            if np.random.random() < 0.5:  # 50% chance of a black module
                stimulus[
                    y * module_size : (y + 1) * module_size,
                    x * module_size : (x + 1) * module_size,
                ] = 1

    # Add QR code-like finder patterns in corners
    finder_size = 7 * (
        module_size // 10
    )  # Adjust finder pattern size based on module size

    def add_finder_pattern(top, left):
        stimulus[top : top + finder_size, left : left + finder_size] = 1
        stimulus[
            top + module_size : top + finder_size - module_size,
            left + module_size : left + finder_size - module_size,
        ] = 0
        stimulus[
            top + 2 * module_size : top + finder_size - 2 * module_size,
            left + 2 * module_size : left + finder_size - 2 * module_size,
        ] = 1

    # Add finder patterns in three corners
    add_finder_pattern(0, 0)  # Top-left
    add_finder_pattern(0, width - finder_size)  # Top-right
    add_finder_pattern(height - finder_size, 0)  # Bottom-left

    return stimulus


class StaticImageStimulus(Stimulus):
    def __init__(self, config):
        super().__init__(config)
        self.surface = self._create_surface(config)

    def _create_surface(self, config):
        if "image" in config:
            return self._load_image(config["image"])
        else:
            return self._generate_qr_like_stimuli(config)

    def _load_image(self, image_path):
        image = pygame.image.load(image_path).convert()
        return pygame.transform.scale(
            image,
            (
                self.config.get("width", SCREEN_WIDTH),
                self.config.get("height", SCREEN_HEIGHT),
            ),
        )

    def _generate_qr_like_stimuli(self, config):
        width = config.get("width", SCREEN_WIDTH)
        height = config.get("height", SCREEN_HEIGHT)
        module_size = config.get("module_size", 10)
        stimulus = generate_qr_like_stimuli(width, height, module_size)
        return pygame.surfarray.make_surface(stimulus * 255)

    def update(self, screen, time_elapsed):
        screen.blit(self.surface, (0, 0))


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
