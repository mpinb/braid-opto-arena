"""
Visual Controller Module

This module controls the display of visual stimuli in a closed-loop system.
It receives input from a ZMQ channel and processes it to display visual stimuli
based on the position and heading direction of tracked objects.
"""

import argparse
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Type
import logging
import sys

# Performance optimization: Use ujson if available
try:
    import ujson as json_parser
except ImportError:
    import json as json_parser

# Disable debugger warning about frozen modules
os.environ["PYDEVD_DISABLE_FILE_VALIDATION"] = "1"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"

import pygame
import yaml
import zmq

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.csv_writer import CsvWriter
from src.core.messages import Subscriber
from visual_stimuli import (
    GratingStimulus,
    LoomingStimulus,
    StaticImageStimulus,
    Stimulus,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("VisualController")

# Constants
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 128
FPS = 60


@dataclass
class DisplayConfig:
    """Configuration for display settings."""

    width: int = SCREEN_WIDTH
    height: int = SCREEN_HEIGHT
    fps: int = FPS
    flags: int = pygame.HWSURFACE | pygame.DOUBLEBUF | pygame.NOFRAME


class StimulusManager:
    """
    Manages the lifecycle and updates of visual stimuli.

    This class handles stimulus creation, updates, and management, providing
    a centralized way to control multiple stimuli types.
    """

    STIMULUS_TYPES: Dict[str, Type[Stimulus]] = {
        "static": StaticImageStimulus,
        "looming": LoomingStimulus,
        "grating": GratingStimulus,
    }

    def __init__(self, config: dict):
        """
        Initialize the StimulusManager with configuration.

        Args:
            config: Dictionary containing stimulus configurations
        """
        self.stimuli = self._create_stimuli(config)
        self._background_stim = None
        self._active_stim = None
        self._initialize_stimuli()

    def _create_stimuli(self, config: dict) -> List[Stimulus]:
        """Create stimulus objects from configuration."""
        stimuli = []
        for stim_config in config["stimuli"]:
            if not stim_config.get("enabled", False):
                continue

            stimulus_class = self.STIMULUS_TYPES.get(stim_config["type"])
            if stimulus_class:
                stimuli.append(stimulus_class(stim_config))
            else:
                logger.warning(f"Unknown stimulus type '{stim_config['type']}'")

        return stimuli

    def _initialize_stimuli(self):
        """Separate static background and active stimuli."""
        for stim in self.stimuli:
            if isinstance(stim, StaticImageStimulus):
                self._background_stim = stim
            elif isinstance(stim, LoomingStimulus):
                self._active_stim = stim

    def update_all(self, screen: pygame.Surface, elapsed: int):
        """
        Update all stimuli in the correct order.

        Args:
            screen: Pygame surface to draw on
            elapsed: Time elapsed since last update in milliseconds
        """
        # Always update background first
        if self._background_stim:
            self._background_stim.update(screen, elapsed)

        # Then update active stimulus if any
        if self._active_stim:
            self._active_stim.update(screen, elapsed)

    def handle_trigger(self, heading_direction: Optional[float]) -> Optional[dict]:
        """
        Handle incoming trigger for active stimulus.

        Args:
            heading_direction: Direction of heading in radians

        Returns:
            dict: Updated trigger information if available
        """
        if self._active_stim and isinstance(self._active_stim, LoomingStimulus):
            self._active_stim.start_expansion(heading_direction)
            return self._active_stim.get_trigger_info()
        return None


class DisplayController:
    """
    Controls the display and processing of visual stimuli.

    This class handles the main display loop, message processing,
    and resource management for the visual stimulus system.
    """

    def __init__(
        self,
        config_path: str,
        braid_folder: str = "",
        standalone: bool = False,
        display_config: Optional[DisplayConfig] = None,
    ):
        self.config_path = config_path
        self.braid_folder = braid_folder
        self.standalone = standalone
        self.display_config = display_config or DisplayConfig()

        self.screen = None
        self.clock = None
        self.stimulus_manager = None
        self.csv_writer = None
        self.subscriber = None

        self._initialize_display()
        self._load_configuration()

    def _initialize_display(self):
        """Initialize pygame display with hardware acceleration."""
        pygame.init()
        self.screen = pygame.display.set_mode(
            (self.display_config.width, self.display_config.height),
            self.display_config.flags,
        )
        pygame.display.set_caption("Stimulus Display")
        self.clock = pygame.time.Clock()

    def _load_configuration(self):
        """Load and process configuration file."""
        with open(self.config_path, "r") as f:
            config = yaml.safe_load(f)

        self.stimulus_manager = StimulusManager(config["visual_stimuli"])

        if not self.standalone:
            self.csv_writer = CsvWriter(os.path.join(self.braid_folder, "stim.csv"))
            self.subscriber = Subscriber(
                address="127.0.0.1", port=config["zmq"]["port"], topics="trigger"
            )
            self.subscriber.initialize()

    def _process_message(self) -> None:
        """Process incoming ZMQ message with minimal overhead."""
        try:
            topic, message = self.subscriber.receive(blocking=False)
            if message is None:
                return

            if message == "kill":
                raise KeyboardInterrupt

            trigger_info = json_parser.loads(message)
            heading_direction = trigger_info.get("heading")

            updated_info = self.stimulus_manager.handle_trigger(heading_direction)
            if updated_info:
                trigger_info.update(updated_info)
                self.csv_writer.write_row(trigger_info)

        except (zmq.ZMQError, json.JSONDecodeError) as e:
            logger.error(f"Message processing error: {e}")

    def run(self):
        """Run the main display loop."""
        logger.info("Starting main display loop")
        try:
            while True:
                elapsed = self.clock.tick(self.display_config.fps)

                if not self.standalone:
                    self._process_message()

                self.screen.fill((255, 255, 255))
                self.stimulus_manager.update_all(self.screen, elapsed)
                pygame.display.flip()

        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down...")
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources and shut down properly."""
        if not self.standalone:
            if self.csv_writer:
                self.csv_writer.close()
            if self.subscriber:
                self.subscriber.close()

        pygame.display.quit()
        pygame.quit()


def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(description="Optimized Stimulus Display Program")
    parser.add_argument(
        "--config_file",
        default="config.yaml",
        type=str,
        help="Path to the configuration file (.yaml)",
    )
    parser.add_argument(
        "--braid_folder",
        type=str,
        default="",
        help="Base directory to save stim.csv",
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        default=False,
        help="Run without ZMQ communication",
    )

    args = parser.parse_args()

    controller = DisplayController(
        config_path=args.config_file,
        braid_folder=args.braid_folder,
        standalone=args.standalone,
    )
    controller.run()


if __name__ == "__main__":
    main()
