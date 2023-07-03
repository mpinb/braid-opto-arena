import logging
import os
from queue import Empty, Queue
from threading import Barrier, Event

import pygame

from .CSVWriter import CSVWriter
from .stimuli import GratingStim, LoomingCircleStim, StaticStim
from .ThreadClass import ThreadClass

os.environ["SDL_VIDEO_WINDOW_POS"] = "%d,%d" % (0, 0)

HEIGHT = 128
WIDTH = 640


class VisualStimuli(ThreadClass):
    """_summary_

    Args:
        ThreadClass (_type_): _description_
    """

    def __init__(
        self,
        queue: Queue,
        kill_event: Event,
        barrier: Barrier,
        params: dict,
        *args,
        **kwargs,
    ) -> None:
        """_summary_

        Args:
            queue (Queue): _description_
            kill_event (Event): _description_
            barrier (Barrier): _description_
            params (dict): _description_
        """
        super(VisualStimuli, self).__init__(
            queue, kill_event, barrier, params, *args, **kwargs
        )
        self.folder = params["folder"]
        self.parse_params()

    def parse_params(self):
        """_summary_"""  # Parse parameters
        self.looming = self.params["stim_params"]["looming"]
        self.static = self.params["stim_params"]["static"]
        self.grating = self.params["stim_params"]["grating"]

    def run(self):
        """_summary_"""
        csv_queue = Queue()

        # Start csv writer
        csv_writer = CSVWriter(
            self.folder + "/opto.csv",
            csv_queue,
            self.kill_event,
        )

        # Start the main pygame instance
        logging.debug("Initializing pygame.")
        pygame.init()
        self._define_screen()

        # Initialize clock
        clock = pygame.time.Clock()

        # Initialize stimuli
        self._define_stimuli()

        # Initialize trigger flag
        trigger_set = False
        loom_status = False

        # Wait for barrier
        logging.debug("Waiting for barrier.")
        print(
            f"VisualStimuli parties: {self.barrier.parties}, n_waiting: {self.barrier.n_waiting}"
        )
        self.barrier.wait()

        # Start the CSV writer
        csv_writer.start()

        # Start main loop
        logging.info("Starting main loop.")
        while not self.kill_event.is_set():
            pass

            # Get data from queue (also acts as trigger)
            try:
                data = self.queue.get_nowait()
                trigger_set = True
                logging.debug("Got data from queue.")
            except Empty:
                trigger_set = False
                pass

            if self.static["active"]:
                self.static_stim.draw()

            # If the trigger is set, check if any stimuli are active
            if trigger_set or loom_status:
                # If the looming stimulus is active, loom it
                if self.looming["active"]:
                    loom_status = self.looming_stim.loom()

                    # If the stimulus is done looming, reset the trigger flag
                    if loom_status is False:
                        trigger_set = False

                csv_queue.put(data)

            # Update window
            pygame.display.flip()

            # Tick clock (60hz refresh rate)
            clock.tick(60)

        # Terminate pygame
        pygame.quit()
        logging.info("Main loop terminated.")

    def _define_screen(self):
        """_summary_"""
        self.screen_size = self.params["stim_params"]["window"]["size"]
        self.screen = pygame.display.set_mode(self.screen_size, pygame.NOFRAME)

    def _define_stimuli(self):
        """_summary_"""

        # Static stimuli
        if self.static["active"]:
            self.static_stim = StaticStim(
                screen=self.screen,
                color=None,
                image=self.static["image"],
            )

        # Grating stimuli
        if self.looming["active"]:
            self.looming_stim = LoomingCircleStim(
                screen=self.screen,
                color=self.looming["color"],
                radius=self.looming["max_radius"],
                duration=self.looming["duration"],
                position=self.looming["position"],
            )
