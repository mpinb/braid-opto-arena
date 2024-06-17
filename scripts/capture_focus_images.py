import numpy as np
import cv2
from ximea import xiapi
from opto import Opto
import time
import argparse
from tqdm import tqdm
import os
from find_best_focus_point import find_best_focus_point, detect_blur_fft
import pandas as pd


def open_controller(dev="/dev/ttyACM0"):
    o = Opto(dev)
    o.connect()
    return o


def open_camera():
    cam = xiapi.Camera()
    cam.open_device()
    cam.set_exposure(1500)
    return cam


def find_optimal_focus_for_liquid_lens(
    position: float, current: int, move_range: int = 10
):
    o = open_controller()
    cam = open_camera()

    img = xiapi.Image()

    cam.start_acquisition()

    current_array = np.arange(current - move_range, current + move_range, 1)

    # create calibration folder if it doesn't exist
    try:
        save_path = f"/home/buchsbaum/calibration/{position:.1f}/"
        os.makedirs(save_path)
    except FileExistsError:
        pass

    repeats = 10

    currents = []
    means = []

    for i, curr in enumerate(tqdm(current_array, desc="Capturing images")):
        o.current(curr)
        time.sleep(0.5)

        for j in range(repeats):
            cam.get_image(img)
            data = img.get_image_data_numpy()

            # save grayscale image to disk
            cv2.imwrite(f"{save_path}/{j}_{curr}.png", data)

            # detect blur
            mean, _ = detect_blur_fft(data)
            time.sleep(0.1)

            currents.append(curr)
            means.append(mean)

    pd.DataFrame({"current": currents, "mean": means}).to_csv(f"{save_path}/data.csv")

    cam.stop_acquisition()
    cam.close_device()
    o.close(soft_close=True)
    return save_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--position", type=float)
    parser.add_argument("--current", type=int)
    parser.add_argument("--range", type=int, default=10)
    args = parser.parse_args()

    position = args.position
    current = args.current
    move_range = args.range

    save_path = find_optimal_focus_for_liquid_lens(position, current, move_range)
    find_best_focus_point(save_path)
