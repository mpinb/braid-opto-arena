import logging
from threading import Event, Barrier
import time
from queue import Queue, Empty

import serial

from ThreadClass import ThreadClass
from CSVWriter import CSVWriter


class OptoTrigger(ThreadClass):
    def __init__(
        self,
        queue: Queue,
        kill_event: Event,
        barrier: Barrier,
        params: dict,
        *args,
        **kwargs,
    ) -> None:
        super(OptoTrigger, self).__init__(
            queue, kill_event, barrier, params, *args, **kwargs
        )

        # Get opto parameters
        self.duration = params["opto_params"]["duration"]
        self.intensity = params["opto_params"]["intensity"]
        self.frequency = params["opto_params"]["frequency"]

        # Get arduino parameters
        self.arduino_device = params["arduino_devices"]["opto_trigger"]

        # Get folder
        self.folder = params["folder"]

    def run(self):
        # Define csv writer queue
        csv_queue = Queue()

        # Start csv writer
        csv_writer = CSVWriter(
            self.folder + "/opto_trigger.csv",
            csv_queue,
            self.kill_event,
        )

        # Start the arduino
        self.connect_to_arduino()

        # Wait for all processes/threads to start
        logging.debug("Reached barrier.")
        self.barrier.wait()

        # Start the CSV writer
        csv_writer.start()

        # Start main loop
        logging.info("Starting main loop.")
        while not self.kill_event.is_set():
            # Get data from queue
            try:
                data = self.queue.get(block=False, timeout=0.01)
            except Empty:
                continue

            data["opto_trigger_get_time"] = time.time()

            # Trigger arduino
            self.trigger()
            data["opto_trigger_to_arduino_time"] = time.time()

            # Save information to csv
            csv_queue.put(data)

        logging.info("Main loop terminated.")

        # Empty queue
        while not self.queue.empty():
            self.queue.get()
        logging.debug("Queue emptied.")

        # Close arduino
        self.board.close()
        logging.debug("Arduino closed.")

    def connect_to_arduino(self):
        self.board = serial.Serial(self.arduino_device, 9600)

    def trigger(self):
        self.board.write(
            f"<{self.duration},{self.intensity},{self.frequency}>".encode()
        )
