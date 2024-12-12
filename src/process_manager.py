# ./src/process_manager.py
import logging
import os
import subprocess

import shlex

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(name="Process manager")


def start_process(command: list):
    """
    Start a new process using the given command.

    Args:
        command (list): A list of strings representing the command and its arguments.

    Returns:
        subprocess.Popen: The Popen object representing the started process.

    Raises:
        None

    Example:
        >>> start_process(['ls', '-l'])
        <subprocess.Popen object at 0x7f955c005b10>
    """
    logger.info(f"Starting process: {os.path.basename(command[0])}")
    process = subprocess.Popen(command)
    return process


def start_visual_stimuli_process(config_path: str, braid_folder: str):
    """
    Start a new process to run the visual stimuli controller.

    Args:
        config_path (str): The path to the configuration file.
        braid_folder (str): The path to the braid folder.

    Returns:
        subprocess.Popen: The Popen object representing the started process.

    Raises:
        None
    """
    command = shlex.split(
        f"/home/buchsbaum/miniforge3/envs/braid-opto-arena-env/bin/python src/stimuli/visual_controller.py --config_file {config_path} --braid_folder {braid_folder}"
    )
    return start_process(command)


def start_ximea_camera_process(videos_folder: str):
    """
    Start a new process to run the Ximea camera and save videos in the specified folder.

    Args:
        videos_base_folder (str): The base folder where the videos will be saved.
        braid_folder (str): The folder containing the braid data.

    Returns:
        subprocess.Popen: The Popen object representing the started process.

    Raises:
        None

    Example:
        >>> start_ximea_camera_process('/path/to/videos', '/path/to/braid')
        <subprocess.Popen object at 0x7f955c005b10>
    """
    # # set and create videos folder
    # videos_folder = os.path.join(
    #     videos_base_folder, os.path.basename(braid_folder)
    # ).split(".")[0]
    # os.makedirs(videos_folder, exist_ok=True)

    # run command
    command = shlex.split(
        f"libs/ximea_camera/target/release/ximea_camera --save-folder {videos_folder}"
    )
    return start_process(command)


# def start_liquid_lens_process(braid_url: str, lens_driver_port: str, braid_folder: str):
#     """
#     Start a new process to run the LiquidLens controller with the specified parameters.

#     Args:
#         braid_url (str): The URL of the Braid server.
#         lens_driver_port (str): The port to connect to the lens driver.
#         braid_folder (str): The folder containing the Braid data.

#     Returns:
#         subprocess.Popen: The Popen object representing the started process.

#     Example:
#         >>> start_liquid_lens_process('http://example.com', '1234', '/path/to/braid')
#         <subprocess.Popen object at 0x7f955c005b10>
#     """
#     command = shlex.split(
#         f"libs/lens_controller/target/release/lens_controller --braid-url {braid_url}:8397 --lens-driver-port {lens_driver_port} --max-update-interval-ms 20 --save-folder {braid_folder}"
#     )
#     return start_process(command)


def start_liquid_lens_process(
    braid_url: str,
    lens_port: str,
    config_file: str = None,
    map_file: str = None,
    video_folder_path: str = None,
    debug: bool = False,
):
    """
    Start a new process to run the tracking script with the specified parameters.

    Args:
        flydra2_url (str): The URL of the flydra2 server.
        lens_port (str): The port to connect to the lens driver.
        zone_file (str): Path to the YAML file defining the tracking zone.
        map_file (str): Path to the CSV file mapping Z values to diopter values.
        debug (bool): Enable debug logging if True.

    Returns:
        subprocess.Popen: The Popen object representing the started process.

    Example:
        >>> start_tracking_process('http://example.com:8397', '/dev/ttyUSB0', 'zone.yaml', 'map.csv', True)
        <subprocess.Popen object at 0x7f955c005b10>
    """
    command = [
        "/home/buchsbaum/miniforge3/envs/braid-opto-arena-env/bin/python",
        "src/lens_controller.py",
        "--braid_url",
        braid_url,
        "--lens_port",
        lens_port,
    ]

    if config_file:
        command.append("--zone_file")
        command.append(config_file)

    if map_file:
        command.append("--map_file")
        command.append(map_file)

    if video_folder_path:
        command.append("--video_folder_path")
        command.append(video_folder_path)

    command.append("--mode")
    command.append("current")

    if debug:
        command.append("--debug")

    return subprocess.Popen(command)
