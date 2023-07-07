import csv
import json
import logging
import os
import pathlib
import time
import serial


def check_braid_folder(root_folder: str) -> str:
    """A simple function to check (and block) until a folder is created.

    Args:
        root_folder (str): the root location where we expect the .braid folder to be created.

    Returns:
        str: the path to the .braid folder.
    """
    p = pathlib.Path(root_folder)
    curr_braid_folder = list(p.glob("*.braid"))

    # loop and test as long as a folder doesn't exist
    if len(curr_braid_folder) == 0:
        logging.info(f"Waiting for .braid folder to be created in {root_folder}....")

    while len(curr_braid_folder) == 0:
        time.sleep(1)
        p = pathlib.Path(root_folder)
        curr_braid_folder = list(p.glob("*.braid"))

    logging.info(f"\nFolder {curr_braid_folder[0].as_posix()} found.")

    return curr_braid_folder[0].as_posix()


def parse_chunk(chunk):
    """function to parse incoming chunks from the flydra2 server

    Args:
        chunk (_type_): _description_

    Returns:
        data: a dict-formatted data object
    """
    DATA_PREFIX = "data: "
    lines = chunk.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "event: braid"
    assert lines[1].startswith(DATA_PREFIX)
    buf = lines[1][len(DATA_PREFIX) :]
    data = json.loads(buf)
    return data


def create_arduino_device(port: str, baudrate: int = 9600) -> serial.Serial:
    """Simple wrapper function to create an arduino device.

    Args:
        port (str): arduino address
        baudrate (int, optional): baudrate parameter. Defaults to 9600.

    Returns:
        serial.Serial: a `board` object
    """
    board = serial.Serial(port, baudrate=baudrate, timeout=1)
    return board


def create_csv_writer(folder: str, file: str):
    # Open csv file
    csv_file = open(os.path.join(folder, file), "a+")

    # Initialize csv writer
    logging.debug("Initializing csv writer.")
    csv_writer = csv.writer(csv_file, delimiter=",")
    if os.stat(csv_file.name).st_size == 0:
        write_header = True
    else:
        write_header = False

    return csv_file, csv_writer, write_header
