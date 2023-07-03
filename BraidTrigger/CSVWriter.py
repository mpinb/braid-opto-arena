import csv
import logging
from queue import Empty, Queue
from threading import Event

from .ThreadClass import ThreadClass


class CSVWriter(ThreadClass):
    """_summary_

    Args:
        ThreadClass (_type_): _description_
    """

    def __init__(
        self,
        filename: str,
        queue: Queue,
        kill_event: Event,
        *args,
        **kwargs,
    ) -> None:
        """_summary_

        Args:
            filename (str): _description_
            queue (Queue): _description_
            kill_event (Event): _description_
        """
        super(CSVWriter, self).__init__(queue, kill_event, *args, **kwargs)

        # Set filename
        self.filename = filename

    def run(self):
        """_summary_"""
        # Open/Create file to append data
        logging.debug(f"Opening file {self.filename}")
        with open(self.filename, "a+", newline="") as csvfile:
            # Initialize csv writer
            logging.debug("Initializing csv writer.")
            csv_writer = csv.writer(csvfile, delimiter=",")

            # Check if file has header
            try:
                header = next(csv_writer)  # noqa: F841
                has_header = True
            except StopIteration:
                has_header = False

            # Start main loop
            logging.info("Starting main loop.")
            while not self.kill_event.is_set():
                try:
                    row = self.queue.get_nowait()
                except Empty:
                    continue

                # Write header if needed
                if not has_header:
                    csv_writer.writerow(row.keys())

                # Write row
                csv_writer.writerow(row.values())

                # Flush to file
                csvfile.flush()

        logging.info("Main loop terminated.")


if __name__ == "__main__":
    c = CSVWriter(
        filename="test.csv", queue=Queue(), kill_event=Event(), name="test", daemon=True
    )

    print(c.name, c.daemon, c.filename, c.queue, c.kill_event)
