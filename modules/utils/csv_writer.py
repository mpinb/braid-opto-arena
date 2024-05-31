import csv


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
        self.write_header = self.check_header()
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

        Returns:
            bool: True if the header row needs to be written, False otherwise.
        """
        self.csv_file.seek(0)  # Move to the beginning of the file to read the first row
        reader = csv.reader(self.csv_file)
        try:
            first_row = next(reader)
            return not all(not str(item).isdigit() for item in first_row)
        except StopIteration:
            return True

    def close(self):
        """
        Closes the CSV file.

        """
        self.csv_file.close()
