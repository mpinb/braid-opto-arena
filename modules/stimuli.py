import pygame
import zmq
import json
import argparse
import os
from messages import Subscriber
import logging

class Stimulus:
    def __init__(self, screen):
        self.screen = screen

    def update(self):
        raise NotImplementedError("Each stimulus must define an update method.")

    def render(self):
        raise NotImplementedError("Each stimulus must define a render method.")

class StaticStimulus(Stimulus):
    def __init__(self, screen, image_path):
        super().__init__(screen)
        self.image_path = image_path
        self.bg = pygame.image.load(image_path)
        self.bg = pygame.transform.scale(
            self.bg, (self.screen.get_width(), self.screen.get_height())
        )

    def update(self):
        pass

    def render(self):
        self.screen.blit(self.bg, (0, 0))

class LoomingStimulus(Stimulus):
    def __init__(
        self,
        screen,
        position,
        initial_size,
        final_size,
        color,
        duration,
        expansion_type="linear",
    ):
        super().__init__(screen)
        self.position = position
        self.initial_size = initial_size
        self.current_size = initial_size
        self.final_size = final_size
        self.color = pygame.Color(color)
        self.duration = duration
        self.expansion_type = expansion_type
        self.expansion_rate = (final_size - initial_size) / (
            duration * 60
        )  # assuming 60 FPS

    def update(self):
        if self.current_size < self.final_size:
            if self.expansion_type == "linear":
                self.current_size += self.expansion_rate
            elif self.expansion_type == "exponential":
                self.current_size *= 1.05  # Example rate, adjust as necessary

    def render(self):
        pygame.draw.circle(
            self.screen, self.color, self.position, int(self.current_size)
        )


class GratingStimulus(Stimulus):
    def __init__(self, screen, width, speed, color):
        super().__init__(screen)
        self.width = width
        self.speed = speed
        self.color = pygame.Color(color)
        self.offset = 0

    def update(self):
        self.offset = (self.offset + self.speed) % self.screen.get_width()

    def render(self):
        num_bars = int(self.screen.get_width() / self.width) + 2
        for i in range(num_bars):
            x = (i * self.width * 2 + self.offset) % (
                self.screen.get_width() + self.width
            ) - self.width
            pygame.draw.rect(
                self.screen, self.color, (x, 0, self.width, self.screen.get_height())
            )


class StimuliDisplay:
    def __init__(
        self, server_ip="localhost", sub_port=5556, handshake_port=5557, refresh_rate=60
    ):
    
        # Initialize zmq variables
        self.server_ip = server_ip
        self.sub_port = sub_port
        self.handshake_port = handshake_port
        self.subscriber = None

        # Initialize display variables
        self.refresh_rate = refresh_rate
        self.screen = None
        self.stimuli = {}

    def setup_display(self, screen_resolution=(640, 128)):

        logging.debug(f"Process {os.getpid()} setting up display")
        # Set the position of the window to the top left corner
        os.environ["SDL_VIDEO_WINDOW_POS"] = "%d,%d" % (0, 0)
        # Initialize the display
        pygame.init()
        self.screen = pygame.display.set_mode(screen_resolution, pygame.NOFRAME)
        pygame.display.set_caption("Fly Tracking Stimuli Display")

    def setup_zmq(self, server_ip="localhost", sub_port=5556, handshake_port=5557):
        logging.debug(f"Process {os.getpid()} setting up zmq")
        # Initialize the subscriber
        self.subscriber = Subscriber(server_ip, sub_port, handshake_port)
        self.subscriber.subscribe("")
        self.subscriber.handshake()

    def run(self):
        logging.info("Starting display server")
        # Initialize the display and zmq
        self.setup_zmq()
        self.setup_display()

        clock = pygame.time.Clock()

        # Main loop
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    logging.debug("Received quit event")
                    break

            try:
                msg = self.socket.recv_string(zmq.NOBLOCK)
            except zmq.Again:
                msg = None

            if msg == "kill":
                logging.debug("Received kill message")
                break
            elif msg:
                self.handle_message(msg)

            self.update_and_render_stimuli()
            pygame.display.flip()
            clock.tick(self.refresh_rate)

        pygame.quit()

    def handle_message(self, msg):
        # Parse the message and create the appropriate stimulus
        try:
            data = json.loads(msg)
            if "type" in data:
                if data["type"] == "looming":
                    self.stimuli["looming"] = LoomingStimulus(
                        self.screen,
                        (data["x"], data["y"]),
                        data["initial_size"],
                        data["final_size"],
                        data["color"],
                        data["duration"],
                        data["expansion_type"],
                    )
                elif data["type"] == "grating":
                    self.stimuli["grating"] = GratingStimulus(
                        self.screen, data["width"], data["speed"], data["color"]
                    )
                elif data["type"] == "static":
                    self.stimuli["static"] = StaticStimulus(
                        self.screen, data["image_path"]
                    )

        except json.JSONDecodeError:
            print("Received non-JSON message:", msg)

    def update_and_render_stimuli(self):
        self.screen.fill((255, 255, 255))  # Clear screen with black
        for key, value in self.stimuli.items():
            value.update()
            value.render()
            
            # Remove looming stimuli that have reached their final size
            if (
                isinstance(value, LoomingStimulus)
                and value.current_size >= value.final_size
            ):
                del self.stimuli[key]

# To run the display
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stimuli Display")
    parser.add_argument(
        "--server_ip", type=str, default="localhost", help="Server IP address"
    )
    parser.add_argument(
        "--sub_port", type=int, default=5556, help="Subscriber port number"
    )
    parser.add_argument(
        "--handshake_port", type=int, default=5557, help="Handshake port number"
    )
    args = parser.parse_args()

    display = StimuliDisplay(args.server_ip, args.sub_port, args.handshake_port)
    display.run()
