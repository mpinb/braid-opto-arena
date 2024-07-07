import cv2

# Set the matplotlib backend to TkAgg
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from opto import Opto
from scipy.optimize import curve_fit
from ximea import xiapi

import faulthandler

faulthandler.enable()


matplotlib.use("TkAgg")


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
    cam.enable_aeag()
    cam.set_exp_priority(1.0)
    cam.set_ae_max_limit(2000)
    cam.set_aeag_level(75)
    return cam


def open_controller(dev="/dev/optotune_ld"):
    o = Opto(dev)
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


def autofocus():
    # open camera and controller
    cam = open_camera()
    lens = open_controller()

    # default diopter settings
    min_dpt = -3
    max_dpt = 2
    step_size_initial = 0.4
    step_size_fine = 0.02

    diopter_settings = np.arange(min_dpt, max_dpt, step_size_initial)
    contrast_values = []
    cam.start_acquisition()

    # take images at different diopter settings
    for dpt in diopter_settings:
        image = take_image(cam, lens, dpt)

        image, contrast = calculate_contrast(image)
        display_image(image, dpt)
        contrast_values.append(contrast)

    contrast_values = np.array(contrast_values)
    max_contrast_idx = np.argmax(contrast_values)
    best_dpt = diopter_settings[max_contrast_idx]

    if max_contrast_idx == 0 or max_contrast_idx == len(diopter_settings) - 1:
        print(f"Warning: Best focus at edge of initial range at {best_dpt} dpt")
        return best_dpt

    fine_dpt_range = np.arange(
        best_dpt - step_size_initial * 1.5,
        best_dpt + step_size_initial * 1.5,
        step_size_fine,
    )
    fine_contrast_values = []

    for dpt in fine_dpt_range:
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
        maxfev=10000,
    )

    best_focus_dpt = popt[0]

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
    plt.savefig("autofocus_plot_0.156.png")
    plt.close("all")
    cam.stop_acquisition()
    return best_focus_dpt


if __name__ == "__main__":
    best_focus = autofocus()
    print(f"The best focus is at {best_focus:.3f} dpt")
