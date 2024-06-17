import os
import ffmpeg
from tqdm.contrib.concurrent import process_map
from tqdm import tqdm
import shutil
from natsort import natsorted


def list_subfolders(folder_path):
    # List to hold all subfolders
    subfolders = []

    # Walk through the directory
    for root, dirs, files in os.walk(folder_path):
        for name in dirs:
            subfolder_path = os.path.join(root, name)
            subfolders.append(subfolder_path)

    return subfolders


def tiff2vid(folder: str):
    try:
        vid_name = os.path.join(folder + ".mp4")
        # create video
        (
            ffmpeg.input(
                os.path.join(folder, "*.tiff"),
                pattern_type="glob",
                framerate=25,
            )
            .output(
                vid_name,
                vcodec="hevc_nvenc",
                preset="p5",
            )
            .run()
        )
    except Exception as e:
        print(f"Error converting {folder} to video, {e}")

    # delete the folder `folder`
    shutil.rmtree(folder)


def main(root_folder: str, concurrent: bool = False, nproc: int = 8):
    # if recurse, get list of all subfolders
    folders = natsorted(list_subfolders(root_folder))
    if len(folders) == 0:
        folders = [root_folder]

    if not concurrent:
        for folder in tqdm(folders):
            tiff2vid(folder)
    else:
        process_map(tiff2vid, folders, max_workers=nproc)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root_folder", type=str, required=False)
    args = parser.parse_args()

    main(args.root_folder)
