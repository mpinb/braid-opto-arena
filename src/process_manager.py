import logging
import os
import subprocess

import shelx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def start_process(command: str):
    logger.info(f"Starting process: {command[0]}")
    process = subprocess.Popen(command, shell=True)
    return process


def start_visual_stimuli_process(config_path: str, braid_folder: str):
    command = shelx.split(
        f"./stimuli/visual_stimuli.py {config_path} --base_dir {braid_folder}"
    )
    return start_process(command)


def start_ximea_camera_process(videos_base_folder: str, braid_folder: str):
    # set and create videos folder
    videos_folder = os.path.join(videos_base_folder, os.path.basename(braid_folder))
    os.makedirs(videos_folder, exist_ok=True)

    # run command
    command = shelx.split(
        f"../libs/ximea_camera/target/release/ximea_camera --save-folder {videos_folder}"
    )
    return start_process(command)


def start_liquid_lens_process(braid_url: str, lens_driver_port: str, braid_folder: str):
    command = shelx.split(
        f"../libs/lens_controller/target/release/lens_controller --braid-url {braid_url} --lens-driver-port {lens_driver_port} --update-interval-ms 20 --save-folder {braid_folder}"
    )
    return start_process(command)
