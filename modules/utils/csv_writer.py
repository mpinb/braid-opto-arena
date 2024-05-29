# csv_writer.py
import csv
import os


class CsvWriter:
    """
    A class for writing data to a CSV file.

    Args:
        filename (str): The name of the CSV file to write to.

    Attributes:
        filename (str): The name of the CSV file.
        csv_file (file): The file object representing the CSV file.
        write_header (bool): A flag indicating whether to write the header row.
        csv_writer (csv.writer): The CSV writer object.

    Methods:
        write(data): Writes a row of data to the CSV file.
        check_header(): Checks if the header row needs to be written.
        close(): Closes the CSV file.

    """

    def __init__(self, filename):
        self.filename = filename
        self.csv_file = open(filename, "a+")
        self.write_header = True
        self.csv_writer = csv.writer(self.csv_file)

    def write(self, data):
        """
        Writes a row of data to the CSV file.

        Args:
            data (dict): A dictionary containing the data to write.

        """
        if self.write_header:
            self.csv_writer.writerow(data.keys())
            self.write_header = False
        self.csv_writer.writerow(data.values())
        self.csv_file.flush()

    def check_header(self):
        """
        Checks if the header row needs to be written.

        This method checks if the CSV file is empty. If it is not empty, it sets the `write_header` flag to False.

        """
        if os.stat(self.filename).st_size > 0:
            self.write_header = False

    def close(self):
        """
        Closes the CSV file.

        """
        self.csv_file.close()
