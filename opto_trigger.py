import copy
import logging
import multiprocessing as mp
import threading
import time
from queue import Queue, Empty

import csv
import os
import serial

from csv_writer import CsvWriter


class OptoTrigger:
    def __init__(
        self,
        queue: Queue,
        kill_event: threading.Event,
        barrier: threading.Barrier,
        params: dict,
    ) -> None:
        # Threading stuff
        self.queue = queue
        self.kill_event = kill_event
        self.barrier = barrier

        # Get opto parameters
        self.duration = params["opto_params"]["duration"]
        self.intensity = params["opto_params"]["intensity"]
        self.frequency = params["opto_params"]["frequency"]

        # Get arduino parameters
        self.arduino_device = params["arduino_devices"]["opto_trigger"]

        # Get folder
        self.folder = params["folder"]

    def run(self):
        # Start csv writer
        self.start_csv_writer()

        # Start the arduino
        self.connect_to_arduino()

        # Wait for all processes/threads to start
        logging.debug("Reached barrier.")
        self.barrier.wait()

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
            self.write_to_csv(data)

        logging.info("Main loop terminated.")

        # Empty queue
        while not self.queue.empty():
            self.queue.get()
        logging.debug("Queue emptied.")

        # Close arduino
        self.board.close()
        logging.debug("Arduino closed.")

        # Close csv file
        self.csv_file.close()
        logging.debug("CSV file closed.")

    def connect_to_arduino(self):
        self.board = serial.Serial(self.arduino_device, 9600)

    def trigger(self):
        self.board.write(
            f"<{self.duration},{self.intensity},{self.frequency}>".encode()
        )

    def start_csv_writer(self):
        # Set csv file path
        csv_file_path = os.path.join(self.folder, "opto.csv")

        # Open CSV file and create writer
        self.csv_file = open(csv_file_path, "a+", newline="")
        self.csv_writer = csv.writer(self.csv_file)

        # This is a way to check if the file is empty
        try:
            header = next(self.csv_writer)  # noqa: F841
            self.has_header = True
        except StopIteration:
            self.has_header = False

    def write_to_csv(self, row):
        # Write header if needed
        if not self.has_header:
            self.csv_writer.writerow(row.keys())
            self.has_header = True

        # Write row
        self.csv_writer.writerow(row.values())

        # Flush to file
        self.csv_file.flush()
