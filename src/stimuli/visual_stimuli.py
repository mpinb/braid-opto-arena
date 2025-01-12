"""
Visual Stimuli Module

This module implements various visual stimuli types for psychophysics experiments.
It provides a flexible framework for creating and managing different types of visual
stimuli, with optimizations for performance and memory usage.

"""

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple, Union, Dict, Any
import logging

import numpy as np
import pygame
import pandas as pd

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("VisualStimuli")

# Constants
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 128
CENTER_Y = SCREEN_HEIGHT // 2

# Set window position (moved from global scope to avoid side effects)
os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"


@dataclass
class StimulusConfig:
    """Configuration dataclass for stimulus parameters."""

    type: str
    enabled: bool = True
    color: Union[str, Tuple[int, int, int]] = "black"
    position_type: str = "random"
    expansion_type: str = "exponential"
    end_radius: Union[int, str] = 64
    duration: Union[int, str] = 150

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "StimulusConfig":
        """Create a StimulusConfig instance from a dictionary."""
        return cls(**{k: v for k, v in config.items() if k in cls.__annotations__})


class Stimulus(ABC):
    """Abstract base class for all visual stimuli."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the stimulus with configuration.

        Args:
            config: Dictionary containing stimulus parameters
        """
        self.config = StimulusConfig.from_dict(config)
        self._surface: Optional[pygame.Surface] = None

    @abstractmethod
    def update(self, screen: pygame.Surface, time_elapsed: int) -> None:
        """
        Update the stimulus state and draw to screen.

        Args:
            screen: Pygame surface to draw on
            time_elapsed: Time elapsed since last update in milliseconds
        """
        pass


class StaticImageStimulus(Stimulus):
    """A stimulus that displays a static image or random pattern."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._surface = self._create_surface()

    def _create_surface(self) -> pygame.Surface:
        """Create the surface based on configuration."""
        if self.config.type == "random":
            return self._generate_random_stimuli()
        return self._load_image(self.config.type)

    @staticmethod
    def _load_image(image_path: str) -> pygame.Surface:
        """Load and optimize an image from disk."""
        try:
            surface = pygame.image.load(image_path).convert()
            return surface
        except pygame.error as e:
            logger.error(f"Failed to load image {image_path}: {e}")
            # Return a default surface on error
            return pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))

    def _generate_random_stimuli(
        self, width: int = SCREEN_WIDTH, height: int = SCREEN_HEIGHT, ratio: int = 8
    ) -> pygame.Surface:
        """Generate random checkerboard pattern."""
        if width % ratio != 0 or height % ratio != 0:
            raise ValueError("Width and height must be divisible by ratio")

        # Optimize numpy operations
        shape = (height // ratio, width // ratio)
        stimulus = np.random.choice([0, 255], size=shape)

        # Create surface directly from numpy array
        surface = pygame.surfarray.make_surface(stimulus)
        return pygame.transform.scale(surface, (width, height))

    def update(self, screen: pygame.Surface, time_elapsed: int) -> None:
        """Update the static image (just blit)."""
        screen.blit(self._surface, (0, 0))


class LoomingStimulus(Stimulus):
    """A stimulus that creates an expanding circle effect."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._setup_expansion_parameters()
        self._initialize_state()

        # Cache commonly used values
        self._color = pygame.Color(self.config.color)
        self._position_calculator = self._create_position_calculator()

    def _setup_expansion_parameters(self) -> None:
        """Set up parameters for expansion behavior."""
        self._expansion_generators = {
            "exponential": self._generate_exponential_looming,
            "natural": self._generate_natural_looming,
        }

        # Pre-calculate constants for natural looming
        self._natural_looming_params = {"l_v": 10, "distance": 25, "hz": 60}

    def _initialize_state(self) -> None:
        """Initialize stimulus state variables."""
        self.expanding = False
        self.position: Optional[int] = None
        self.start_time: Optional[float] = None
        self.curr_frame = 0
        self.radii_array: Optional[np.ndarray] = None

    def _create_position_calculator(self):
        """Create appropriate position calculation function."""
        if self.config.position_type == "random":
            return lambda _: np.random.randint(0, SCREEN_WIDTH)
        elif self.config.position_type == "closed-loop":
            return self._calculate_closed_loop_position
        return lambda _: self.config.position_type

    @staticmethod
    def _calculate_closed_loop_position(heading_direction: Optional[float]) -> int:
        """Calculate position based on heading direction."""
        if heading_direction is None:
            return np.random.randint(0, SCREEN_WIDTH)

        # Cache the calibration data
        if not hasattr(LoomingStimulus, "_calibration_data"):
            try:
                df = pd.read_csv("src/stimuli/calibration.csv")
                LoomingStimulus._calibration_data = {
                    "heading": df["angle"].values,
                    "screen": df["circle"].values,
                }
            except Exception as e:
                logger.error(f"Failed to load calibration data: {e}")
                return np.random.randint(0, SCREEN_WIDTH)

        return int(
            np.interp(
                heading_direction,
                LoomingStimulus._calibration_data["heading"],
                LoomingStimulus._calibration_data["screen"],
                period=2 * np.pi,
            )
        )

    def _generate_natural_looming(
        self, max_radius: float, duration: float
    ) -> np.ndarray:
        """Generate natural looming radius progression."""
        params = self._natural_looming_params
        n_frames = int(duration / (1000 / params["hz"]))

        # Vectorized computation
        indices = np.arange(1, n_frames)
        r = 2 * np.arctan(params["l_v"] / indices)
        looming_size = np.tan(r / 2) * params["distance"]

        # Normalize and scale
        looming_size = (looming_size - looming_size.min()) / (
            looming_size.max() - looming_size.min()
        )
        return np.flip(looming_size * max_radius)

    def _generate_exponential_looming(
        self, max_radius: float, duration: float
    ) -> np.ndarray:
        """Generate exponential looming radius progression."""
        n_frames = int(duration / (1000 / 60))
        return np.logspace(0, np.log10(max_radius), n_frames)

    def start_expansion(self, heading_direction: Optional[float] = None) -> None:
        """Start the looming expansion effect."""
        if self.expanding:
            return

        # Get parameters
        max_radius = (
            np.random.randint(32, 64)
            if self.config.end_radius == "random"
            else self.config.end_radius
        )
        duration = (
            np.random.randint(150, 500)
            if self.config.duration == "random"
            else self.config.duration
        )

        # Calculate position
        self.position = self._position_calculator(heading_direction)

        # Generate radius progression
        self.radii_array = self._expansion_generators[self.config.expansion_type](
            max_radius, duration
        )

        # Initialize expansion state
        self.start_time = time.time()
        self.curr_frame = 0
        self.n_frames = len(self.radii_array)
        self.expanding = True

    def update(self, screen: pygame.Surface, time_elapsed: int) -> None:
        """Update and draw the looming stimulus."""
        if not self.expanding or self.curr_frame >= self.n_frames - 1:
            self.expanding = False
            return

        radius = self.radii_array[self.curr_frame]
        position = self.position % SCREEN_WIDTH

        # Draw main circle
        pygame.draw.circle(screen, self._color, (position, CENTER_Y), int(radius))

        # Handle wrap-around
        if position - radius < 0:
            pygame.draw.circle(
                screen, self._color, (position + SCREEN_WIDTH, CENTER_Y), int(radius)
            )
        if position + radius > SCREEN_WIDTH:
            pygame.draw.circle(
                screen, self._color, (position - SCREEN_WIDTH, CENTER_Y), int(radius)
            )

        self.curr_frame += 1

    def get_trigger_info(self) -> Dict[str, Any]:
        """Get current stimulus information for logging."""
        return {
            "timestamp": time.time(),
            "stimulus": self.config.expansion_type,
            "expansion": self.expanding,
            "position": self.position,
            "max_radius": self.config.end_radius,
            "duration": self.config.duration,
            "color": self.config.color,
        }


class GratingStimulus(Stimulus):
    """A stimulus that displays moving gratings."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self._initialize_grating_parameters()

    def _initialize_grating_parameters(self) -> None:
        """Initialize grating-specific parameters."""
        self.frequency = self.config.frequency
        self.direction = self.config.direction
        self._color = pygame.Color(self.config.color)

    def update(self, screen: pygame.Surface, time_elapsed: int) -> None:
        """Update and draw the grating stimulus."""
        # Placeholder for grating implementation
        pass
