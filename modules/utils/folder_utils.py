# folder_utils.py
import os
import time
import logging
import pathlib


def check_braid_folder(root_folder: str) -> str:
    """
    Check if a .braid folder exists in the specified root folder.
    If the folder does not exist, wait until it is created.

    Args:
        root_folder (str): The root folder to check for the .braid folder.

    Returns:
        str: The path of the first .braid folder found.
    """
    p = pathlib.Path(root_folder)
    curr_braid_folder = list(p.glob("*.braid"))

    if len(curr_braid_folder) == 0:
        logging.info(f"Waiting for .braid folder to be created in {root_folder}....")

    while len(curr_braid_folder) == 0:
        time.sleep(1)
        p = pathlib.Path(root_folder)
        curr_braid_folder = list(p.glob("*.braid"))

    logging.info(f"\nFolder {curr_braid_folder[0].as_posix()} found.")

    return curr_braid_folder[0].as_posix()


def check_braid_running(root_folder: str, debug: bool) -> str:
    if not debug:
        return check_braid_folder(root_folder)
    else:
        os.makedirs("test/", exist_ok=True)
        return "test/"
