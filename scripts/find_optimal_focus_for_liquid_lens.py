import numpy as np
import pandas as pd
import cv2
from ximea import xiapi
from opto import Opto
import time
import argparse
from skimage.measure import shannon_entropy
from tqdm import tqdm


def open_controller(dev="/dev/ttyACM0"):
    o = Opto(dev)
    o.connect()
    return o


def open_camera():
    cam = xiapi.Camera()
    cam.open_device()
    cam.set_exposure(2000)
    return cam


def calculate_laplacian_focus(image):
    laplacian = cv2.Laplacian(image, cv2.CV_64F)
    focus_metric = laplacian.var()
    return focus_metric


def calculate_sobel_focus(image):
    sobelx = cv2.Sobel(image, cv2.CV_64F, 1, 0, ksize=5)
    sobely = cv2.Sobel(image, cv2.CV_64F, 0, 1, ksize=5)
    focus_metric = np.mean(np.hypot(sobelx, sobely))
    return focus_metric


def calculate_variance_of_intensity(image):
    focus_metric = np.var(image)
    return focus_metric


def calculate_entropy(image):
    focus_metric = shannon_entropy(image)
    return focus_metric


def calculate_focus_metrics(image_gray):
    metrics = {
        "laplacian": calculate_laplacian_focus(image_gray),
        "sobel": calculate_sobel_focus(image_gray),
        "variance_intensity": calculate_variance_of_intensity(image_gray),
        "entropy": calculate_entropy(image_gray),
    }
    return metrics


def normalize_metrics(metrics):
    normalized_metrics = {}
    for key, values in metrics.items():
        normalized_metrics[key] = (values - np.min(values)) / (
            np.max(values) - np.min(values)
        )
    return normalized_metrics


def compute_composite_score(normalized_metrics, weights):
    composite_score = np.zeros(len(next(iter(normalized_metrics.values()))))
    for key, values in normalized_metrics.items():
        composite_score += values * weights[key]
    return composite_score


def find_optimal_focus_for_liquid_lens(position: float, current: int):
    o = open_controller()
    cam = open_camera()

    img = xiapi.Image()

    cam.start_acquisition()

    current_array = np.arange(current - 50, current + 50, 1)
    focus_metrics = {
        key: np.zeros(len(current_array))
        for key in ["current", "laplacian", "sobel", "variance_intensity", "entropy"]
    }

    for i, curr in enumerate(tqdm(current_array)):
        time.sleep(1)
        o.current(curr)
        time.sleep(0.1)
        cam.get_image(img)
        data = img.get_image_data_numpy()
        metrics = calculate_focus_metrics(data)

        focus_metrics["current"][i] = curr
        for key in metrics:
            focus_metrics[key][i] = metrics[key]

        # resize frame by a factor of 4
        image_resized = cv2.cvtColor(
            cv2.resize(data, (data.shape[1] // 4, data.shape[0] // 4)),
            cv2.COLOR_GRAY2BGR,
        )
        cv2.putText(
            image_resized,
            f"{curr}",
            (50, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.imshow("Image", image_resized)
        cv2.waitKey(1)

    normalized_metrics = normalize_metrics(
        {k: v for k, v in focus_metrics.items() if k != "current"}
    )

    # Define weights for each focus metric
    weights = {
        "laplacian": 0.25,
        "sobel": 0.25,
        "variance_intensity": 0.2,
        "entropy": 0.15,
    }

    composite_scores = compute_composite_score(normalized_metrics, weights)
    best_focus_index = np.argmax(composite_scores)
    best_focus_current = current_array[best_focus_index]

    print(
        f"Best Focus Found at Current: {best_focus_current}, Composite Score: {composite_scores[best_focus_index]}"
    )

    df = pd.DataFrame(focus_metrics)
    df["composite_score"] = composite_scores
    df.to_csv(f"{position}_calibration_matrix.csv", index=False)

    cam.stop_acquisition()
    cam.close_device()
    o.close(soft_close=True)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--position", type=float)
    parser.add_argument("--current", type=int)
    args = parser.parse_args()
    position = args.position
    current = args.current

    find_optimal_focus_for_liquid_lens(position, current)
