import matplotlib

matplotlib.use("Qt5Agg")  # Force Matplotlib to use PyQt5
import matplotlib.pyplot as plt

import numpy as np
import cv2
import os
import natsort
from tqdm.contrib.concurrent import process_map


def detect_blur_fft(image, size=60, threshold=10):
    (h, w) = image.shape
    (cx, cy) = (int(w / 2.0), int(h / 2.0))
    fft = np.fft.fft2(image)
    fftShift = np.fft.fftshift(fft)

    fftShift[cy - size : cy + size, cx - size : cx + size] = 0
    fftShift = np.fft.ifftshift(fftShift)
    recon = np.fft.ifft2(fftShift)

    magnitude = 20 * np.log(np.abs(recon))
    mean = np.mean(magnitude)

    return (mean, mean <= threshold)


def process_file(args):
    file, folder = args
    current = os.path.splitext(os.path.basename(file))[0]
    image_path = os.path.join(folder, file)

    if not os.path.exists(image_path):
        print(f"File not found: {image_path}")
        return (current, None)

    image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        print(f"Failed to read image: {image_path}")
        return (current, None)

    mean, blurry = detect_blur_fft(image, size=60, threshold=10)
    return (current, mean)


def is_filename_numeric(filename):
    name, ext = os.path.splitext(filename)
    return name.isdigit()


def find_best_focus_point(folder: str):
    files = os.listdir(folder)
    files = natsort.natsorted([f for f in files if f.endswith(".png")])
    files = [file for file in files if is_filename_numeric(file)]

    args = [(file, folder) for file in files]
    results = process_map(process_file, args, max_workers=os.cpu_count())

    files_values = []
    fft_values = []
    for file, fft_value in results:
        if fft_value is not None:
            files_values.append(file)
            fft_values.append(fft_value)

    plt.figure()
    plt.plot(files_values, fft_values)
    plt.ylabel("Blur Value")
    plt.xlabel("Image")
    plt.xticks(rotation=90)
    max_file_value = files_values[np.argmax(fft_values)]
    plt.title(f"{max_file_value}")
    plt.tight_layout()
    plt.savefig(f"{folder}/focus_values.png")
    plt.close("all")

    np.savetxt(
        f"{folder}/focus_values.csv",
        np.column_stack([files_values, fft_values]),
        delimiter=",",
        fmt="%s",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=str, required=False)
    args = parser.parse_args()

    find_best_focus_point(args.folder)
