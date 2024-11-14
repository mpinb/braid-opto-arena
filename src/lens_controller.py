import argparse
import logging
import time
import yaml
import json
from typing import Dict, Any
from dataclasses import dataclass
from devices.lens_driver import LensDriver
from messages import Subscriber
from braid_proxy import BraidProxy
import pandas as pd
import numpy as np
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LinearRegression
import csv
import os

# Set up logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants
MIN_UPDATE_INTERVAL = 1 / 100  # Minimum time between lens updates
DEFAULT_LENS_UPDATE_DURATION = 3.0  # Time to wait for updates after trigger
STATS_REPORT_INTERVAL = 100  # Number of updates between stats reporting


@dataclass
class PerformanceStats:
    updates: int = 0
    misses: int = 0
    total_latency: float = 0.0

    def log_stats(self):
        if self.updates == 0:
            return
        avg_latency = self.total_latency / self.updates
        logger.info(
            f"Performance Stats: "
            f"Average latency: {avg_latency:.3f}s, "
            f"Updates: {self.updates}, "
            f"Misses: {self.misses}"
        )


class LensCalibration:
    def __init__(self, z_values, dpt_values, method="poly", degree=2):
        self.z_values = np.array(z_values)
        self.dpt_values = np.array(dpt_values)
        self.method = method

        if method == "poly":
            self.model = make_pipeline(PolynomialFeatures(degree), LinearRegression())
            self.model.fit(z_values.reshape(-1, 1), dpt_values)
        else:
            raise ValueError("Method must be 'poly'")

        # Calculate and log fit metrics
        pred_values = self.get_dpt(self.z_values)
        residuals = self.dpt_values - pred_values
        metrics = {
            "rmse": np.sqrt(np.mean(residuals**2)),
            "max_error": np.max(np.abs(residuals)),
            "mean_error": np.mean(np.abs(residuals)),
        }
        logger.debug(f"Lens calibration metrics: {metrics}")

    def get_dpt(self, z):
        """Get diopter value for given z position(s)."""
        z = np.asarray(z)
        return self.model.predict(z.reshape(-1, 1))[0]


def setup_lens_calibration(interp_file: str) -> LensCalibration:
    """Set up the lens calibration model."""
    try:
        interp_data = pd.read_csv(interp_file)
        z_values, dpt_values = interp_data["z"].values, interp_data["dpt"].values
        return LensCalibration(z_values, dpt_values, method="poly", degree=2)
    except Exception as e:
        logger.error(f"Error setting up lens calibration: {e}")
        raise


def update_lens(
    lens_driver: LensDriver, z: float, calibration: LensCalibration, mode: str
) -> float:
    """Update lens position with error handling."""
    try:
        value = float(
            calibration.get_dpt(z)
        )  # Convert to float in case numpy type is returned

        if mode == "current":
            lens_driver.set_current(value)
        elif mode == "diopter":
            lens_driver.set_diopter(value)

        logger.debug(f"Updated lens to {mode}={value} for z={z}")
        return value
    except Exception as e:
        logger.error(f"Error updating lens: {e}")
        raise


def validate_config(config: Dict[str, Any]) -> None:
    """Validate the configuration file has all required fields."""
    required_fields = {"braid": ["url", "event_port", "control_port"], "zmq": ["port"]}

    for section, fields in required_fields.items():
        if section not in config:
            raise ValueError(f"Missing required config section: {section}")
        for field in fields:
            if field not in config[section]:
                raise ValueError(f"Missing required config field: {section}.{field}")


def create_csv_writer(video_folder_path: str, obj_id: str, frame: str) -> tuple:
    """Create CSV writer with dynamic filename based on message contents."""
    filename = f"obj_id_{obj_id}_frame_{frame}_liquid_lens.csv"
    csv_path = os.path.join(video_folder_path, filename)
    
    fields = [
        "trigger_recv_time",
        "msg_recv_time",
        "frame_timestamp",
        "lens_update_time",
        "z",
        "diopter/current",
    ]

    try:
        csv_file = open(csv_path, "w", newline="")
        writer = csv.writer(csv_file)
        writer.writerow(fields)
        logger.info(f"Created new CSV file: {csv_path}")
        return writer, csv_file
    except Exception as e:
        logger.error(f"Error creating CSV file: {e}")
        raise


def run_tracking(
    braid_url: str,
    lens_port: str,
    config_file: str,
    interp_file: str,
    video_folder_path: str = None,
    mode: str = "current",
    debug: bool = False,
    lens_update_duration: float = DEFAULT_LENS_UPDATE_DURATION,
) -> None:
    # Validate inputs
    assert mode in ["current", "diopter"], "mode must be either 'current' or 'diopter'"
    assert video_folder_path is not None, "video_folder_path must be provided"

    # Load and validate config
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)
    validate_config(config)

    # Setup lens calibration
    calibration = setup_lens_calibration(interp_file)

    # Initialize performance stats
    stats = PerformanceStats()

    # Use context managers for resource management
    with (
        BraidProxy(
            base_url=config["braid"]["url"],
            event_port=config["braid"]["event_port"],
            control_port=config["braid"]["control_port"],
        ) as braid_proxy,
        Subscriber(
            address="127.0.0.1", port=config["zmq"]["port"], topics="trigger"
        ) as subscriber,
        LensDriver(port=lens_port, debug=debug) as lens_driver,
    ):
        lens_driver.set_mode(mode)
        current_csv_writer = None
        current_csv_file = None

        try:
            while True:
                # Receive message
                try:
                    topic, message = subscriber.receive()
                    trigger_recv_time = time.time()
                except Exception as e:
                    logger.error(f"Error receiving message: {e}")
                    continue

                # Process message
                if message == "kill":
                    raise KeyboardInterrupt

                try:
                    trigger_info = json.loads(message)
                    obj_id = trigger_info["obj_id"]
                    frame = trigger_info.get("frame", "unknown")  # Get frame from message
                    frame_timestamp = trigger_info.get("timestamp", 0)

                    # Close previous CSV file if exists
                    if current_csv_file is not None:
                        current_csv_file.close()

                    # Create new CSV writer for this message
                    current_csv_writer, current_csv_file = create_csv_writer(
                        video_folder_path, obj_id, frame
                    )

                except (json.JSONDecodeError, KeyError) as e:
                    logger.error(f"Error processing message: {e}")
                    continue

                lens_updated = False
                update_start_time = time.time()

                # Update lens position
                for event in braid_proxy.iter_events():
                    if event is None:
                        continue

                    msg_recv_time = time.time()
                    try:
                        msg_dict = event["msg"]
                        if "Update" in msg_dict:
                            msg_dict = msg_dict["Update"]
                            if msg_dict["obj_id"] == obj_id:
                                z = msg_dict["z"]

                                # Update lens
                                value = update_lens(lens_driver, z, calibration, mode)
                                lens_update_time = time.time()
                                lens_updated = True

                                # Record data
                                if current_csv_writer:
                                    current_csv_writer.writerow(
                                        [
                                            trigger_recv_time,
                                            msg_recv_time,
                                            frame_timestamp,
                                            lens_update_time,
                                            z,
                                            value,
                                        ]
                                    )
                                    current_csv_file.flush()

                                # Update stats
                                stats.updates += 1
                                stats.total_latency += (
                                    lens_update_time - trigger_recv_time
                                )
                                if stats.updates % STATS_REPORT_INTERVAL == 0:
                                    stats.log_stats()

                                time.sleep(MIN_UPDATE_INTERVAL)
                    except Exception as e:
                        logger.error(f"Error processing event: {e}")
                        continue

                    if time.time() - update_start_time > lens_update_duration:
                        break

                if not lens_updated:
                    logger.warning(f"No matching events found for object {obj_id}")
                    stats.misses += 1

                # Reset lens position
                lens_driver.ramp_to_zero()

                # Close CSV file
                current_csv_file.close()
                current_csv_file = None

        except KeyboardInterrupt:
            logger.info("Shutting down...")
            stats.log_stats()  # Log final stats
        finally:
            # Ensure the last CSV file is properly closed
            if current_csv_file is not None:
                current_csv_file.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="3D Object Tracking and Lens Control")
    parser.add_argument(
        "--braid_url", help="URL for the braid server", default="http://127.0.0.1:8397/"
    )
    parser.add_argument(
        "--lens_port", help="Port for the lens controller", default="/dev/optotune_ld"
    )
    parser.add_argument(
        "--config-file",
        default="/home/buchsbaum/src/braid-opto-arena/config.yaml",
        help="YAML file defining the tracking zone",
    )
    parser.add_argument(
        "--interp-file",
        default="/home/buchsbaum/liquid_lens_calibration_20241112.csv",
        help="CSV file mapping Z values to diopter values",
    )
    parser.add_argument(
        "--mode",
        default="current",
        help="Mode for the lens controller (current or diopter)",
    )
    parser.add_argument("--video_folder_path", default=None, help="Path to save videos")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--lens-update-duration",
        type=float,
        default=DEFAULT_LENS_UPDATE_DURATION,
        help="Maximum duration to wait for lens updates after trigger (seconds)",
    )
    args = parser.parse_args()

    run_tracking(
        args.braid_url,
        args.lens_port,
        args.config_file,
        args.interp_file,
        args.video_folder_path,
        args.mode,
        args.debug,
        args.lens_update_duration,
    )


if __name__ == "__main__":
    main()
