import csv
import os


class CsvWriter:
    def __init__(self, filename):
        """
        Initializes a CsvWriter object.

        Args:
            filename (str): The name of the file to write to.

        Returns:
            None
        """
        self.filename = filename
        self.file_exists = os.path.isfile(filename)
        self.header_written = False
        self.file = None
        self.writer = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def open(self):
        if not self.file:
            mode = "a" if self.file_exists else "w"
            self.file = open(self.filename, mode, newline="")

    def close(self):
        if self.file:
            self.file.close()
            self.file = None
            self.writer = None

    def write_row(self, row_dict):
        """
        Writes a row to the CSV file.

        Args:
            row_dict (dict): A dictionary representing a row of data to be written.

        Returns:
            None

        This method checks if the file is open. If not, it opens the file in append mode.
        It then checks if the writer is initialized. If not, it initializes the writer
        with the fieldnames from the row_dict. If the file does not exist or the header
        has not been written yet, it writes the header and sets the header_written flag
        to True. Finally, it writes the row_dict to the file and flushes the buffer.
        """
        if not self.file:
            self.open()

        if not self.writer:
            fieldnames = list(row_dict.keys())
            self.writer = csv.DictWriter(self.file, fieldnames=fieldnames)

            if not self.file_exists or not self.header_written:
                self.writer.writeheader()
                self.header_written = True
                self.file_exists = True

        self.writer.writerow(row_dict)
        self.file.flush()
