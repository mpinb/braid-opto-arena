# file_utils.py
import os
import shutil
import logging
import filecmp
from tqdm.contrib.concurrent import thread_map
import git


def copy_files_with_progress(src_folder, dest_folder):
    """
    Copy files from the source folder to the destination folder with progress.

    Args:
        src_folder (str): The path to the source folder.
        dest_folder (str): The path to the destination folder.

    Returns:
        None
    """

    def copy_file(src_file_path, dest_file_path):
        shutil.copy2(src_file_path, dest_file_path)

        if filecmp.cmp(src_file_path, dest_file_path, shallow=False):
            logging.debug(f"File {src_file_path} copied successfully.")
            os.remove(src_file_path)

    files = [
        f for f in os.listdir(src_folder) if os.path.isfile(os.path.join(src_folder, f))
    ]
    src_file_paths = [os.path.join(src_folder, file) for file in files]
    dest_file_paths = [os.path.join(dest_folder, file) for file in files]

    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    thread_map(copy_file, src_file_paths, dest_file_paths, max_workers=4)

    if len(os.listdir(src_folder)) == 0:
        os.rmdir(src_folder)


def copy_files_to_folder(folder: str, file: str):
    """
    Copy a file to a specified folder and write the commit hash to a params.toml file.

    Args:
        folder (str): The destination folder where the file will be copied to.
        file (str): The path of the file to be copied.

    Returns:
        None
    """
    shutil.copy(file, folder)
    with open(os.path.join(folder, "params.toml"), "w") as f:
        f.write(
            f"commit = {git.Repo(search_parent_directories=True).head.commit.hexsha}"
        )
