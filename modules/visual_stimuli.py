import pygame
import zmq
import json
import toml
import csv
import time
import argparse
import random
from abc import ABC, abstractmethod

# Constants
SCREEN_WIDTH = 640
SCREEN_HEIGHT = 128


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
        self.image = pygame.image.load(config["path"]).convert()

    def update(self, screen, time_elapsed):
        screen.blit(self.image, (0, 0))


# Looming stimulus
class LoomingStimulus(Stimulus):
    def __init__(self, config):
        super().__init__(config)
        self.max_radius = self._get_value(config["max_radius"], 0, 100)
        self.duration = self._get_value(config["duration"], 150, 500)
        self.color = pygame.Color(config["color"])
        self.position_type = config.get("position", "center")
        self.position = None
        self.start_time = None
        self.expanding = False
        self.type = config["stim_type"]

    def _get_value(self, value, min_val, max_val):
        if value == "random":
            return random.randint(min_val, max_val)
        return value

    def start_expansion(self, heading_direction=None):
        self.max_radius = self._get_value(self.config["max_radius"], 0, 100)
        self.duration = self._get_value(self.config["duration"], 150, 500)
        if self.position_type == "random":
            self.position = self._get_value("random", 0, SCREEN_WIDTH)
        elif self.position_type == "closed-loop" and heading_direction is not None:
            self.position = heading_direction
        else:
            self.position = SCREEN_WIDTH // 2
        self.start_time = time.time()
        self.expanding = True

    def update(self, screen, time_elapsed):
        if self.expanding:
            elapsed = (time.time() - self.start_time) * 1000  # convert to milliseconds
            if elapsed < self.duration:
                if self.type == "linear":
                    radius = (elapsed / self.duration) * self.max_radius
                elif self.type == "exponential":
                    radius = (
                        (2 ** (elapsed / self.duration) - 1) / (2 - 1) * self.max_radius
                    )
                pygame.draw.circle(
                    screen, self.color, (self.position, SCREEN_HEIGHT // 2), int(radius)
                )
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
def main(config_path, standalone):
    # Initialize pygame
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Stimulus Display")

    # Load configuration
    config = toml.load(config_path)

    # Create stimuli
    stimuli = []
    for stim_config in config["stimuli"]:
        if stim_config["type"] == "static":
            stimuli.append(StaticImageStimulus(stim_config))
        elif stim_config["type"] == "looming":
            stimuli.append(LoomingStimulus(stim_config))
        elif stim_config["type"] == "grating":
            stimuli.append(GratingStimulus(stim_config))

    # CSV logging setup
    csv_file = open("stim.csv", mode="a", newline="")
    csv_writer = csv.writer(csv_file)

    # ZMQ setup if not standalone
    context, socket = None, None
    if not standalone:
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.connect("tcp://localhost:5556")
        socket.setsockopt_string(zmq.SUBSCRIBE, "")

    # Main loop
    running = True
    clock = pygame.time.Clock()
    while running:
        time_elapsed = clock.get_time()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_k:
                for stim in stimuli:
                    if isinstance(stim, LoomingStimulus):
                        stim.start_expansion()

        if not standalone:
            try:
                message = socket.recv_string(flags=zmq.NOBLOCK)
                if message == "kill":
                    running = False
                    break
                else:
                    trigger_info = json.loads(message)
                    heading_direction = trigger_info.get("heading_direction")
                    # Handle trigger for looming stimulus
                    for stim in stimuli:
                        if isinstance(stim, LoomingStimulus):
                            stim.start_expansion(heading_direction)
                            updated_info = stim.get_trigger_info()
                            trigger_info.update(updated_info)
                            # Log the event
                            csv_writer.writerow(trigger_info.values())
            except zmq.Again:
                pass  # No message received

        # Update screen
        screen.fill((255, 255, 255))
        for stim in stimuli:
            stim.update(screen, time_elapsed)
        pygame.display.flip()
        clock.tick(60)

    # Clean up
    csv_file.close()
    pygame.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stimulus Display Program")
    parser.add_argument(
        "config_file", type=str, help="Path to the configuration file (.toml)"
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Run the program in standalone mode without ZMQ",
    )
    args = parser.parse_args()

    main(args.config_file, args.standalone)
