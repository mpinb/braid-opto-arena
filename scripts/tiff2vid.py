import os
import warnings

import cv2
from natsort import natsorted
from vidgear.gears import WriteGear
from tqdm.contrib.concurrent import process_map

# Suppress all warnings
warnings.filterwarnings("ignore")

output_params = {
    "-input_framerate": 25,
    "-vcodec": "h264_nvenc",
    "-preset": "p6",
    "-tune": "hq",
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
        return

    video_writer = WriteGear(output=output_filename, logging=False, **output_params)

    # loop over the tiff files
    for frame_file in frame_files:
        frame_path = os.path.join(folder, frame_file)
        image = cv2.imread(frame_path, cv2.IMREAD_UNCHANGED)
        video_writer.write(cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))

    video_writer.close()


def main(root_folder: str):
    # if recurse, get list of all subfolders
    folders = natsorted(list_subfolders(root_folder))
    if len(folders) == 0:
        folders = [root_folder]

    process_map(write_video, folders, max_workers=4)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("root_folder", type=str)
    args = parser.parse_args()

    main(args.root_folder)
