import os
import sys
import time
from ximea import xiapi

import json
import requests
import cv2
import matplotlib.pyplot as plt
import numpy as np

# Get the parent directory of the repository
repository_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(repository_root)
from modules.utils.liquid_lens import LiquidLens  # noqa: E402

OFFSET_X = 1504
WIDTH = 1088

OFFSET_Y = 790
HEIGHT = 600

DATA_PREFIX = "data: "


def flydra_proxy(flydra2_url, queue):
    session = requests.session()
    r = session.get(flydra2_url)
    assert r.status_code == requests.codes.ok

    print("Connected to Flydra2. Listening for events...")
    events_url = flydra2_url + "events"
    r = session.get(
        events_url,
        stream=True,
        headers={"Accept": "text/event-stream"},
    )

    for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
        data = parse_chunk(chunk)
        try:
            update_dict = data["msg"]["Update"]
            queue.put(update_dict)
        except KeyError:
            continue


def parse_chunk(chunk):
    lines = chunk.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "event: braid"
    assert lines[1].startswith(DATA_PREFIX)
    buf = lines[1][len(DATA_PREFIX) :]
    data = json.loads(buf)
    return data


def take_image(cam, lens, diopter):
    img = xiapi.Image()
    # taking an image with the camera at a specific diopter setting

    try:
        lens.set_diopter(diopter)
    except Exception:
        pass

    cam.get_image(img)
    data = img.get_image_data_numpy()
    return data


def _take_image(cam):
    img = xiapi.Image()

    cam.get_image(img)


def calculate_contrast(
    image,
    method="laplacian",
):
    """
    Calculate the RMS contrast of the image.

    Parameters:
    image (np.array): Input image (grayscale).

    Returns:
    float: RMS contrast value.
    """
    # Ensure the image is in grayscale
    if len(image.shape) == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # extract the region of interest
    image_roi = image[OFFSET_Y : OFFSET_Y + HEIGHT, OFFSET_X : OFFSET_X + WIDTH]

    if method == "contrast":
        # Calculate the mean intensity
        mean_intensity = np.mean(image_roi)

        # Calculate the RMS contrast
        contrast = np.sqrt(np.mean((image_roi - mean_intensity) ** 2))

    elif method == "laplacian":
        # Calculate the Laplacian of the image
        laplacian = cv2.Laplacian(image_roi, cv2.CV_64F)

        # calculate the variance of the laplacian
        contrast = laplacian.var()

    return image_roi, contrast


def lorentzian(x, x0, gamma, a, y0):
    return a / (1 + ((x - x0) / gamma) ** 2) + y0


def open_camera():
    cam = xiapi.Camera()
    cam.open_device()
    cam.set_exposure(2000)
    cam.set_imgdataformat("XI_MONO8")
    cam.set_acq_timing_mode("XI_ACQ_TIMING_MODE_FREE_RUN")

    return cam


def open_controller(dev="/dev/optotune_ld"):
    o = LiquidLens(port=dev)
    o.to_focal_power_mode()
    return o


def display_image(image, dpt):
    # make a copy of the image
    image_copy = cv2.cvtColor(image.copy(), cv2.COLOR_GRAY2BGR)

    # display the image
    cv2.imshow("Image", image_copy)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        return True
    return False


def plot_contrast_values(dpt_range, contrast_values, mode):
    # Plotting the results
    plt.figure()
    plt.plot(dpt_range, contrast_values, "o", label="Data points")
    plt.xlabel("Optical power [dpt]")
    plt.ylabel("Contrast value")
    plt.legend()
    plt.savefig(f"/home/buchsbaum/lens_calibration/autofocus_plot_{mode}.png")
    plt.close("all")


def autofocus(z_pos):
    # open camera and controller
    print("Opening camera and controller...")
    cam = open_camera()
    print("Camera opened")
    lens = open_controller()
    print("Controller opened")

    # default diopter settings
    min_dpt = -4.5
    max_dpt = 4.5
    step_size_initial = 0.2
    step_size_fine = 0.02

    print(f"Initial z position: {z_pos:.3f}")

    diopter_settings = np.arange(min_dpt, max_dpt, step_size_initial)
    contrast_values = np.zeros(len(diopter_settings))
    cam.start_acquisition()

    for i in range(10):
        time.sleep(0.01)
        _take_image(cam)

    # take images at different diopter settings
    for i, dpt in enumerate(diopter_settings):
        time.sleep(0.1)
        image = take_image(cam, lens, dpt)
        image, contrast = calculate_contrast(image)
        display_image(image, dpt)
        contrast_values[i] = contrast

    contrast_values = np.array(contrast_values)
    max_contrast_idx = np.argmax(contrast_values)
    best_dpt = diopter_settings[max_contrast_idx]

    plot_contrast_values(diopter_settings, contrast_values, mode="initial")

    print(f"Best initial focus at {best_dpt:.3f} dpt")
    if max_contrast_idx == 0 or max_contrast_idx == len(diopter_settings) - 1:
        print(f"Warning: Best focus at edge of initial range at {best_dpt} dpt")
        return best_dpt

    fine_dpt_range = np.arange(
        best_dpt - (step_size_initial * 2),
        best_dpt + (step_size_initial * 2),
        step_size_fine,
    )
    fine_contrast_values = []

    for dpt in fine_dpt_range:
        time.sleep(0.1)
        image = take_image(cam, lens, dpt)

        image, contrast = calculate_contrast(image)
        display_image(image, dpt)
        fine_contrast_values.append(contrast)
    cv2.destroyAllWindows()

    fine_contrast_values = np.array(fine_contrast_values)
    plot_contrast_values(fine_dpt_range, fine_contrast_values, mode="fine")
    # # save fine contrast values to file for debugging
    # with open(
    #     f"/home/buchsbaum/lens_calibration/fine_contrast_values_zpos_{z_pos}.csv", "w"
    # ) as f:
    #     for i in range(len(fine_dpt_range)):
    #         f.write(f"{fine_dpt_range[i]},{fine_contrast_values[i]}\n")

    cam.stop_acquisition()

    # # write line with best_focus_dpt and distance to file
    # with open(
    #     "/home/buchsbaum/lens_calibration/liquid_lens_calibration.csv", "a+"
    # ) as f:
    #     f.write(f"{best_focus_dpt:.3f},{z_pos:.3f}\n")
    # return best_focus_dpt


if __name__ == "__main__":
    best_focus = autofocus(0.22)
    print(f"The best focus is at {best_focus:.3f} dpt")
