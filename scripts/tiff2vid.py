import os
import warnings

import cv2
from natsort import natsorted
from tqdm import tqdm
from vidgear.gears import WriteGear
from send2trash import send2trash
import logging

# Suppress all warnings
warnings.filterwarnings("ignore")

output_params = {
    "-input_framerate": 25,
    "-vf": "format=gray",
    "-vcodec": "h264_nvenc",
    "-preset": "p7",
    "-tune": "hq",
    "-rc": "vbr_hq",
    "-qmin": 1,
    "-qmax": 25,
    "-b:v": "5M",
    "-maxrate": "10M",
    "-bufsize": "20M",
    "-profile:v": "high",
    "-disable_force_termination": True,
}


def list_subfolders(folder_path):
    # List to hold all subfolders
    subfolders = []

    # Walk through the directory
    for root, dirs, files in os.walk(folder_path):
        for name in dirs:
            subfolder_path = os.path.join(root, name)
            subfolders.append(subfolder_path)

    return subfolders


def write_video(folder):
    frame_files = natsorted([f for f in os.listdir(folder) if f.endswith(".tiff")])

    # if no tiff files, skip
    if len(frame_files) == 0:
        return

    # create videowriter
    output_filename = folder + ".mp4"

    # check if file exists
    if os.path.exists(output_filename):
        # delete the file
        os.remove(output_filename)

    logging.getLogger("WriteGear").setLevel(logging.ERROR)
    video_writer = WriteGear(output=output_filename, logging=False, **output_params)

    # loop over the tiff files
    for frame_file in tqdm(frame_files, leave=False):
        frame_path = os.path.join(folder, frame_file)
        image = cv2.imread(frame_path, cv2.IMREAD_UNCHANGED)
        video_writer.write(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))

    video_writer.close()

    # check if the video was successfully written
    if not os.path.exists(output_filename):
        return
    # if it was, delete the original tiff files
    else:
        send2trash([os.path.join(folder, frame_file) for frame_file in frame_files])


def main(root_folder: str):
    # if recurse, get list of all subfolders
    folders = natsorted(list_subfolders(root_folder))
    if len(folders) == 0:
        folders = [root_folder]

    for folder in tqdm(folders):
        write_video(folder)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("root_folder", type=str)
    args = parser.parse_args()

    main(args.root_folder)
