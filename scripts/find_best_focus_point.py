import os
import sys
import time
from scipy.optimize import curve_fit
from ximea import xiapi

import json
import requests
import cv2
import matplotlib.pyplot as plt
import numpy as np
from modules.utils.liquid_lens import LiquidLens

# Get the parent directory of the repository
repository_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(repository_root)


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
        lens.focalpower(diopter)
    except Exception:
        pass

    cam.get_image(img)
    data = img.get_image_data_numpy()
    return data


def calculate_contrast(
    image, offset_x=1696, offset_y=600, width=960, height=960, method="contrast"
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
    image = image[offset_y : offset_y + height, offset_x : offset_x + width]

    if method == "contrast":
        # Calculate the mean intensity
        mean_intensity = np.mean(image)

        # Calculate the RMS contrast
        contrast = np.sqrt(np.mean((image - mean_intensity) ** 2))

    elif method == "laplacian":
        # Calculate the Laplacian of the image
        laplacian = cv2.Laplacian(image, cv2.CV_64F)

        # calculate the variance of the laplacian
        contrast = laplacian.var()

    return image, contrast


def lorentzian(x, x0, gamma, a, y0):
    return a / (1 + ((x - x0) / gamma) ** 2) + y0


def open_camera():
    cam = xiapi.Camera()
    cam.open_device()
    cam.set_exposure(2000)
    # cam.enable_aeag()
    # cam.set_exp_priority(1.0)
    # cam.set_ae_max_limit(2000)
    # cam.set_aeag_level(75)
    return cam


def open_controller(dev="/dev/optotune_ld"):
    o = LiquidLens(port=dev)
    o.connect()
    o.mode("focal")
    return o


def display_image(image, dpt):
    # make a copy of the image
    image_copy = cv2.cvtColor(image.copy(), cv2.COLOR_GRAY2BGR)

    # display the image
    cv2.imshow("Image", image_copy)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        return True
    return False


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
    step_size_initial = 0.4
    step_size_fine = 0.02

    print(f"Initial z position: {z_pos:.3f}")

    diopter_settings = np.arange(min_dpt, max_dpt, step_size_initial)
    contrast_values = []
    cam.start_acquisition()

    # take images at different diopter settings
    for dpt in diopter_settings:
        time.sleep(0.02)
        image = take_image(cam, lens, dpt)

        image, contrast = calculate_contrast(image)
        display_image(image, dpt)
        contrast_values.append(contrast)

    contrast_values = np.array(contrast_values)
    max_contrast_idx = np.argmax(contrast_values)
    best_dpt = diopter_settings[max_contrast_idx]

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
        time.sleep(0.02)
        image = take_image(cam, lens, dpt)

        image, contrast = calculate_contrast(image)
        display_image(image, dpt)
        fine_contrast_values.append(contrast)
    cv2.destroyAllWindows()

    fine_contrast_values = np.array(fine_contrast_values)
    popt, _ = curve_fit(
        lorentzian,
        fine_dpt_range,
        fine_contrast_values,
        p0=[
            best_dpt,
            step_size_fine,
            np.max(fine_contrast_values),
            np.min(fine_contrast_values),
        ],
        maxfev=1000,
    )

    best_focus_dpt = popt[0]

    # save fine contrast values to file for debugging
    with open(
        f"/home/buchsbaum/lens_calibration/fine_contrast_values_zpos_{z_pos}.csv", "w"
    ) as f:
        for i in range(len(fine_dpt_range)):
            f.write(f"{fine_dpt_range[i]},{fine_contrast_values[i]}\n")

    # Plotting the results
    plt.figure()
    plt.plot(fine_dpt_range, fine_contrast_values, "o", label="Data points")
    plt.plot(
        fine_dpt_range, lorentzian(fine_dpt_range, *popt), "-", label="Lorentzian fit"
    )
    plt.xlabel("Optical power [dpt]")
    plt.ylabel("Contrast value")
    plt.title(f"The best focus is at {best_focus_dpt:.3f} dpt")
    plt.legend()
    plt.savefig(f"/home/buchsbaum/lens_calibration/autofocus_plot_{z_pos:.3f}.png")
    plt.close("all")
    cam.stop_acquisition()

    # write line with best_focus_dpt and distance to file
    with open(
        "/home/buchsbaum/lens_calibration/liquid_lens_calibration.csv", "a+"
    ) as f:
        f.write(f"{best_focus_dpt:.3f},{z_pos:.3f}\n")

    return best_focus_dpt


if __name__ == "__main__":
    best_focus = autofocus(0.22)
    print(f"The best focus is at {best_focus:.3f} dpt")
