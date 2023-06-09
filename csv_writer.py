import csv
import logging
import threading
import os
import queue
import time


class CsvWriter(threading.Thread):
    def __init__(
        self,
        csv_file: str,
        queue=queue.Queue,
        kill_event=threading.Event,
    ):
        super(CsvWriter, self).__init__()

        # get parameters
        self.filename = csv_file

        # threading control
        self.queue = queue
        self.kill_event = kill_event

        # open csv file
        self.csv_file = open(self.filename, "a+")
        self.csv_writer = csv.writer(self.csv_file, delimiter=",")

    def run(self):
        # loop over the queue as long as it's alive
        while True:
            # check for kill event and empty queue
            if self.kill_event.is_set() and self.queue.empty():
                logging.debug("CsvWriter received kill event.")
                break

            # get data
            logging.debug(f"Queue size: {self.queue.qsize()}")
            data = self.queue.get()
            data["csv_writer_receive_time"] = time.time()

            # write data to file
            logging.debug(f"Writing data {data} to {self.filename}")
            self.write_row(data)

        self.csv_file.close()

    def write_row(self, data: list):
        logging.debug(f"Writing row {data} to {self.filename}")

        data["csv_writer_write_time"] = time.time()

        # if the file is empty, write the header
        if self._get_file_size() == 0:
            self.csv_writer.writerow(list(data.keys()))

        # write line
        self.csv_writer.writerow(list(data.values))

        # flush to disk
        self.csv_writer.flush()

    @property
    def _get_file_size(self):
        return os.stat(self.filename).st_size


if __name__ == "__main__":
    pass
