import copy
import logging
import multiprocessing as mp
import os
import random
import threading
import time
import tomllib
from queue import Queue
from ThreadClass import ThreadClass
from threading import Barrier, Event
import pygame

os.environ["SDL_VIDEO_WINDOW_POS"] = "%d,%d" % (0, 0)


class VisualStimuli(ThreadClass):
    def __init__(
        self,
        queue: Queue,
        kill_event: Event,
        barrier: Barrier,
        params: dict,
        *args,
        **kwargs,
    ) -> None:
        super(VisualStimuli, self).__init__(
            queue, kill_event, barrier, params, *args, **kwargs
        )

    def run(self):
        # Start the main pygame instance
        logging.debug("Initializing pygame.")
        pygame.init()
        self._define_screen()

        # Initialize clock
        clock = pygame.time.Clock()

        # Initialize stimuli

        # Wait for barrier
        logging.debug("Waiting for barrier.")
        self.barrier.wait()

        # Start main loop
        logging.info("Starting main loop.")
        while not self.kill_event.is_set():
            pass

            # Update window
            pygame.display.flip()

            # Tick clock (60hz refresh rate)
            clock.tick(60)

        pygame.quit()
        logging.info("Main loop terminated.")

    def _define_screen(self):
        # Define screen size
        self.screen_size = self.params["screen_size"]
        self.screen = pygame.display.set_mode(self.screen_size, pygame.NOFRAME)

    def _define_stimuli(self):
        pass


class LoomingCircleStim:
    def __init__(self) -> None:
        pass


class GratingStim:
    def __init__(self) -> None:
        pass


class StaticStim:
    def __init__(self) -> None:
        pass


def stimuli(
    trigger_event: mp.Event,
    kill_event: mp.Event,
    mp_dict: mp.Manager().dict,
    barrier: mp.Barrier,
    got_trigger_counter: mp.Value,
    lock: mp.Lock,
    params: dict,
):
    # start csv writer
    csv_queue = Queue()
    csv_kill = threading.Event()
    csv_writer = CsvWriter(
        csv_file=params["folder"] + "/stim.csv",
        queue=csv_queue,
        kill_event=csv_kill,
    ).start()

    # initialize pygame
    pygame.init()

    # initialize screen
    WIDTH, HEIGHT = 640, 128
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.NOFRAME)

    # initialize clock
    clock = pygame.time.Clock()

    # background image
    if params["stim_params"]["static"]["active"]:
        bg = pygame.image.load(params["stim_params"]["static"]["image"])
        bg = pygame.transform.scale(bg, (WIDTH, HEIGHT))
    else:
        bg = pygame.Surface((WIDTH, HEIGHT))
        bg.fill("white")

    loom_stim = params["stim_params"]["looming"]["active"]

    # looming stimulus
    if loom_stim:
        circle_color = params["stim_params"]["looming"]["color"]

        circle_duration = params["stim_params"]["looming"]["duration"]
        if circle_duration == "random":
            random_duration = True
            possible_durations = [300, 500]
        else:
            random_duration = False

        # convert the max radius to pixels
        circle_max_radius = params["stim_params"]["looming"]["max_radius"]

        if circle_max_radius == "random":
            random_radius = True
            possible_radius = [32, 64]
        else:
            random_radius = False
            circle_max_radius = int(circle_max_radius / 2 * HEIGHT)

            # calculate the change in radius per frame
            F = circle_duration / (1000 / 60)
            dR = circle_max_radius / F

        # check if the circle position is random
        circle_position = params["stim_params"]["looming"]["position"]
        if circle_position == "random":
            random_position = True
            possible_positions = list(range(0, WIDTH, 32))
        else:
            random_position = False

        radius = 0
        start_loom = False

    # wait barrier
    logging.debug("Waiting for barrier")
    barrier.wait()
    logging.info("Barrier passed")
    trigger = False

    try:
        while True:
            # check if the kill event is set
            if kill_event.is_set():
                break

            # fill the screen with image/color
            screen.blit(bg, (0, 0))
            if trigger_event.is_set() and not trigger:
                data = copy.deepcopy(mp_dict)
                with lock:
                    got_trigger_counter.value += 1
                trigger = True
                logging.info("Got data from trigger event, set counter+=1")

            if loom_stim:
                # test if the trigger event is set
                if trigger and not start_loom:
                    start_loom = True  # set the start_loom flag to True
                    logging.debug("Got data from trigger event")

                    data["stimulus_start_time"] = time.time()

                    # check if random duration
                    if random_duration:
                        circle_duration = random.choice(possible_durations)

                    # check if random radius
                    if random_radius:
                        circle_max_radius = random.choice(possible_radius)
                        F = circle_duration / (1000 / 60)
                        dR = circle_max_radius / F

                    # if the position is random, generate a random position
                    if random_position:
                        x = random.randint(0, random.choice(possible_positions))
                        y = HEIGHT // 2
                    else:
                        x = WIDTH // 2
                        y = HEIGHT // 2

                    data["looming_pos_x"] = x
                    data["looming_pos_y"] = y
                    data["looming_radius"] = circle_max_radius
                    data["looming_duration"] = circle_duration

                    # wait for all other processes to process the trigger
                    csv_queue.put(data)
                    trigger = False

                # if the start_loom flag is set, draw the circle
                if start_loom:
                    radius += dR

                    # once the circle reaches the max radius, reset the radius and set the start_loom flag to False
                    if radius > circle_max_radius:
                        radius = 0
                        start_loom = False

                    # draw the circle
                    pygame.draw.circle(screen, circle_color, (x, y), radius)

                    # wraparound the x position if the circle goes off the screen
                    if x - radius < 0:
                        pygame.draw.circle(screen, circle_color, (x + WIDTH, y), radius)
                    elif x + radius > WIDTH:
                        pygame.draw.circle(screen, circle_color, (x - WIDTH, y), radius)

            pygame.display.flip()
            clock.tick(60)

    except KeyboardInterrupt:
        kill_event.set()

    pygame.quit()
    csv_kill.set()
    try:
        csv_writer.join()
    except AttributeError:
        pass

    logging.info("Stimuli process terminated.")


if __name__ == "__main__":
    trigger_event = mp.Event()
    kill_event = mp.Event()
    mp_dict = mp.Manager().dict()
    barrier = mp.Barrier(1)
    trigger_barrier = mp.Barrier(1)

    with open("params.toml", "rb") as f:
        params = tomllib.load(f)
    params["folder"] = "./test/"
    p = mp.Process(
        target=stimuli,
        args=(
            trigger_event,
            kill_event,
            mp_dict,
            barrier,
            trigger_barrier,
            params,
        ),
    )

    p.start()

    while not kill_event.is_set():
        user_input = input("Press e to trigger stimulus, q to quit: ")
        if user_input == "e":
            trigger_event.set()
            trigger_barrier.wait()
        elif user_input == "q":
            kill_event.set()
            break
        else:
            print("Invalid input.")

    p.join()
