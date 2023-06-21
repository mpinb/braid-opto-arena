import copy
import logging
import multiprocessing as mp
import threading
import time
from queue import Queue

import serial

from csv_writer import CsvWriter


def opto_trigger(
    trigger_event: mp.Event,
    kill_event: mp.Event,
    data_dict: mp.Manager().dict,
    barrier: mp.Barrier,
    reusable_barrier,
    params: dict,
):
    # start csv writer
    csv_queue = Queue()
    csv_kill = threading.Event()
    csv_writer = CsvWriter(
        csv_file=params["folder"] + "/opto.csv",
        queue=csv_queue,
        kill_event=csv_kill,
    ).start()

    # connect to arduino
    board = serial.Serial(params["arduino_devices"]["opto_trigger"], 9600)

    # get parameters from dict
    duration = params["opto_params"]["duration"]
    intensity = params["opto_params"]["intensity"]
    frequency = params["opto_params"]["frequency"]

    # wait for all processes to start
    barrier.wait()
    logging.info("opto_trigger started.")

    # start main loop
    while True:
        # check for kill event
        if kill_event.is_set():
            break

        # wait for trigger event
        if trigger_event.is_set():
            reusable_barrier.wait()
            # if the trigger event got set, trigger the arduino
            logging.debug("OptoTrigger triggered.")
            event_time = time.time()

            # get data from mp dict
            data = copy.deepcopy(data_dict)
            logging.debug(f"Got data: {data}")
            data["opto_trigger_event_set_time"] = event_time
            data["opto_trigger_data_copy_time"] = time.time()

            # send trigger to arduino
            board.write(f"<{duration},{intensity},{frequency}>".encode())
            data["opto_trigger_to_arduino_send_time"] = time.time()
            logging.debug("Sending trigger to arduino")

            # add information regarding the trigger to the data dict
            data["duration"] = duration
            data["intensity"] = intensity
            data["frequency"] = frequency
            data["opto_trigger_to_csv_send_time"] = time.time()

            # send to csv writer
            csv_queue.put(data)
            logging.debug("Writing data to csv")

    board.close()
    csv_kill.set()
    try:
        csv_writer.join()
    except AttributeError:
        pass
    logging.info("opto_trigger stopped.")
