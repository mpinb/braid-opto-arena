import logging
import multiprocessing as mp
import os
import time

import pygame

from helper_functions import create_csv_writer
from stimuli.LoomingStim import LoomingStim
from stimuli.StaticStim import StaticStim


def start_visual_stimuli(
    params: dict, trigger_recv: mp.Pipe, kill_event: mp.Event, args
):
    os.environ["SDL_VIDEO_WINDOW_POS"] = "%d,%d" % (0, 0)
    logging.debug("Initializing pygame.")
    pygame.init()

    width, height = (
        params["stim_params"]["window"]["size"][0],
        params["stim_params"]["window"]["size"][1],
    )  # noqa: E501
    screen = pygame.display.set_mode((width, height), pygame.NOFRAME)
    clock = pygame.time.Clock()

    # Check if static stimulus is active
    if args.static:
        logging.debug("Initializing static stimulus.")
        static_active = True
        static_stim = StaticStim(
            screen=screen, image=params["stim_params"]["static"]["image"]
        )
    else:
        static_active = False

    # Check if grating stimulus is active
    if args.grating:
        logging.debug("Initializing grating stimulus.")
        grating_active = True
        pass
    else:
        grating_active = False

    # Check if looming stimulus is active
    if args.looming:
        logging.debug("Initializing looming stimulus.")
        looming_active = True
        looming_stim = LoomingStim(
            screen=screen,
            color=params["stim_params"]["looming"]["color"],
            radius=params["stim_params"]["looming"]["max_radius"],
            duration=params["stim_params"]["looming"]["duration"],
            position=params["stim_params"]["looming"]["position"],
            stim_type=params["stim_params"]["looming"]["stim_type"],
        )
    else:
        looming_active = False

    # Create looming flags
    do_looming = False
    do_grating = False

    # Start CSV writer object
    csv_file, csv_writer, write_header = create_csv_writer(params["folder"], "stim.csv")

    logging.info("Starting main loop.")
    while not kill_event.is_set():
        if kill_event.is_set():
            break
        # Check if there's anything in the pipe
        trigger_set = trigger_recv.poll()

        # If so, it's the trigger. Also get the data.
        if trigger_set:
            # logging.debug("Trigger received.")
            trigger_data = trigger_recv.recv()

        # Draw static stim
        if static_active:
            # logging.debug("Drawing static stimulus.")
            static_stim.draw()

        # Check if the trigger is set
        if trigger_set:
            # Check if the looming stimulus is active
            if looming_active:
                # Initialize the looming stimulus
                do_looming = looming_stim.init_loom()

                # Get stim data from looming stimulus object
                dict_update_time = time.time()
                trigger_data["radius"] = looming_stim.curr_loom["radius"]
                trigger_data["duration"] = looming_stim.curr_loom["duration"]
                trigger_data["position"] = looming_stim.curr_loom["position"]
                logging.debug(f"Dict update time: {time.time()-dict_update_time:.5f}")

            if grating_active:
                do_grating = True

            # Write data to csv
            logging.debug("Writing data to csv.")
            csv_writer_time = time.time()
            if write_header:
                csv_writer.writerow(trigger_data.keys())
                write_header = False
            csv_writer.writerow(trigger_data.values())
            csv_file.flush()
            logging.debug(f"CSV writer time: {time.time()-csv_writer_time:.5f}")

        if do_looming:
            do_looming = looming_stim.loom()

        if do_grating:
            pass

        # Update screen
        pygame.display.flip()

        # Tick clock (60hz)
        clock.tick(60)

    # Close pygame
    pygame.quit()

    # Close CSV file
    csv_file.close()
    logging.info("Closed pygame.")
