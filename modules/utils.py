import csv
import filecmp
import json
import logging
import os
import pathlib
import shutil
import time
import serial
from tqdm.contrib.concurrent import thread_map


def copy_files_with_progress(src_folder, dest_folder):
    def copy_file(src_file_path, dest_file_path):
        shutil.copy2(src_file_path, dest_file_path)

        if filecmp.cmp(src_file_path, dest_file_path, shallow=False):
            logging.debug(f"File {src_file_path} copied successfully.")
            os.remove(src_file_path)

    # Get a list of all files in the source folder
    files = [
        f for f in os.listdir(src_folder) if os.path.isfile(os.path.join(src_folder, f))
    ]

    src_file_paths = [os.path.join(src_folder, file) for file in files]
    dest_file_paths = [os.path.join(dest_folder, file) for file in files]

    # Make sure the destination folder exists
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    thread_map(copy_file, src_file_paths, dest_file_paths, max_workers=4)

    if len(os.listdir(src_folder)) == 0:
        os.rmdir(src_folder)


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
