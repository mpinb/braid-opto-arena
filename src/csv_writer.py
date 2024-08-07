import csv
import os


class CsvWriter:
    def __init__(self, filename):
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
