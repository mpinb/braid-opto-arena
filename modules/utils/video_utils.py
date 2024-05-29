# video_utils.py
import os


def get_video_output_folder(
    braid_folder: str, base_folder: str = "/home/buchsbaum/mnt/DATA/Videos/"
):
    """
    Get the output folder path for a video based on the braid folder.

    Args:
        braid_folder (str): The path of the braid folder.
        base_folder (str, optional): The base folder where the video output folder will be created. Defaults to "/home/buchsbaum/mnt/DATA/Videos/".

    Returns:
        str: The output folder path for the video.
    """
    base_folder = os.path.splitext(os.path.basename(braid_folder))[0]
    return os.path.join((base_folder, braid_folder))
