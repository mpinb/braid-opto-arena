import os
import ffmpeg


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
                preset="fast",
            )
            .run()
        )
    except:
        print(f"Error converting {folder} to video")

    # delete the folder `folder`
    # shutil.rmtree(folder)


def main(root_folder: str):
    # if recurse, get list of all subfolders
    folders = list_subfolders(root_folder)
    if len(folders) == 0:
        folders = [root_folder]

    # loop over folders
    from tqdm import tqdm

    for folder in tqdm(folders):
        tiff2vid(folder)

    # process_map(tiff2vid, folders, max_workers=8)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root_folder", type=str, required=False)
    args = parser.parse_args()

    main(
        root_folder="/home/buchsbaum/mnt/DATA/Videos/20240418_113218/",
    )
