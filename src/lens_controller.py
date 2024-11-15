import argparse
import csv
import json
import logging
import os
import time
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Thread
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import yaml
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures

from braid_proxy import BraidProxy
from devices.lens_driver import LensDriver
from messages import Subscriber

# Keep existing logging setup and constants
logging.basicConfig(
    level=logging.INFO,
    format="LENSCONTROLLER: %(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Keep existing constants and LensCalibration class
MIN_UPDATE_INTERVAL = 1 / 100
DEFAULT_LENS_UPDATE_DURATION = 3.0
STATS_REPORT_INTERVAL = 100


@dataclass
class TriggerInfo:
    obj_id: str
    frame: str
    timestamp: float
    receive_time: float


@dataclass
class UpdateMessage:
    obj_id: str
    z: float
    trigger_time: float  # Original trigger receive time
    msg_receive_time: float
    frame: str


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
    filename = f"lens_controller_obj_id_{obj_id}_frame_{frame}.csv"
    csv_path = os.path.join(video_folder_path, filename)

    fields = [
        "trigger_recv_time",
        "msg_recv_time",
        "frame_timestamp",
        "lens_update_time",
        "z",
        "diopter_value",
    ]

    csv_file = open(csv_path, "w", newline="")
    writer = csv.writer(csv_file)
    writer.writerow(fields)
    logger.info(f"Created new CSV file: {csv_path}")
    return writer, csv_file


class TriggerProcessor(Thread):
    def __init__(self, config: Dict, trigger_queue: Queue, shutdown_event: Event):
        super().__init__()
        self.config = config
        self.shutdown_event = shutdown_event
        self.trigger_queue = trigger_queue
        self.subscriber = Subscriber(
            address="127.0.0.1", port=config["zmq"]["port"], topics="trigger"
        )
        self.subscriber.initialize()

    def run(self):
        try:
            while not self.shutdown_event.is_set():
                try:
                    topic, message = self.subscriber.receive(blocking=True, timeout=0.1)

                    if message is None:
                        continue

                    if message == "kill" or self.shutdown_event.is_set():
                        break

                    trigger_info = json.loads(message)
                    trigger = TriggerInfo(
                        obj_id=trigger_info["obj_id"],
                        frame=trigger_info.get("frame", "unknown"),
                        timestamp=trigger_info.get("timestamp", time.time()),
                        receive_time=time.time(),
                    )
                    self.trigger_queue.put(trigger)
                    logger.info(
                        f"Received trigger for object {trigger.obj_id}, frame {trigger.frame}"
                    )

                except TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error in trigger processing: {e}")
                    if self.shutdown_event.is_set():
                        break

        finally:
            logger.info("Shutting down TriggerProcessor")
            try:
                self.subscriber.close()
            except Exception as e:
                logger.error(f"Error closing subscriber: {e}")


class BraidStreamProcessor(Thread):
    def __init__(
        self,
        config: Dict,
        trigger_queue: Queue,
        update_queue: Queue,
        shutdown_event: Event,
    ):
        super().__init__()
        self.config = config
        self.trigger_queue = trigger_queue
        self.update_queue = update_queue
        self.shutdown_event = shutdown_event
        self.current_trigger: Optional[TriggerInfo] = None
        self.braid_proxy = None

    def connect_braid(self):
        """Initialize or reconnect to BraidProxy"""
        logger.info("Connecting to BraidProxy...")
        try:
            if self.braid_proxy:
                self.braid_proxy.close()

            self.braid_proxy = BraidProxy(
                base_url=self.config["braid"]["url"],
                event_port=self.config["braid"]["event_port"],
                control_port=self.config["braid"]["control_port"],
                auto_connect=True,
            )
            logger.info("Successfully connected to BraidProxy")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to BraidProxy: {e}")
            return False

    def run(self):
        logger.info("Starting BraidStreamProcessor...")

        while not self.shutdown_event.is_set():
            try:
                if not self.connect_braid():
                    logger.error(
                        "Failed to connect to BraidProxy, retrying in 5 seconds..."
                    )
                    time.sleep(5)
                    continue

                logger.info("Starting event processing loop")
                for event in self.braid_proxy.iter_events():
                    if self.shutdown_event.is_set():
                        logger.info("Shutdown event detected, breaking event loop")
                        break

                    # Check for new trigger (non-blocking)
                    try:
                        while not self.trigger_queue.empty():
                            self.current_trigger = self.trigger_queue.get_nowait()
                            logger.info(
                                f"New trigger received for object {self.current_trigger.obj_id}"
                            )
                    except Empty:
                        pass

                    # Skip non-Update events
                    if not (event.get("msg", {}).get("Update")):
                        continue

                    # Process Update event if we have an active trigger
                    if self.current_trigger:
                        try:
                            msg_dict = event["msg"]["Update"]
                            if msg_dict["obj_id"] == self.current_trigger.obj_id:
                                update = UpdateMessage(
                                    obj_id=self.current_trigger.obj_id,
                                    z=msg_dict["z"],
                                    trigger_time=self.current_trigger.receive_time,
                                    msg_receive_time=time.time(),
                                    frame=self.current_trigger.frame,
                                )
                                self.update_queue.put(update)
                                logger.debug(
                                    f"Processed update for object {update.obj_id}: z={update.z}"
                                )
                        except KeyError as e:
                            logger.error(
                                f"Error processing Update event: {e}, event={event}"
                            )

            except Exception as e:
                if not self.shutdown_event.is_set():
                    logger.error(f"Error in event processing loop: {e}")
                    logger.error("Will attempt to reconnect...")
                    time.sleep(1)
                    continue

        logger.info("BraidStreamProcessor shutting down...")
        if self.braid_proxy:
            try:
                # self.braid_proxy.toggle_recording(start=False)
                self.braid_proxy.close()
            except Exception as e:
                logger.error(f"Error during BraidProxy shutdown: {e}")


class LensController(Thread):
    def __init__(
        self,
        lens_port: str,
        calibration: LensCalibration,
        update_queue: Queue,
        mode: str,
        debug: bool,
        video_folder_path: str,
        shutdown_event: Event,
        tracking_duration: float = 3.0,
    ):
        super().__init__()
        self.update_queue = update_queue
        self.shutdown_event = shutdown_event
        self.lens_driver = LensDriver(port=lens_port, debug=debug)
        self.calibration = calibration
        self.mode = mode
        self.video_folder_path = video_folder_path
        self.tracking_duration = tracking_duration
        self.current_csv_writer = None
        self.current_csv_file = None
        self.current_obj_id = None
        self.tracking_start_time = None

    def run(self):
        logger.info("Starting LensController")
        try:
            self.lens_driver.set_mode(self.mode)

            while not self.shutdown_event.is_set():
                try:
                    # Check if current tracking session should end
                    current_time = time.time()
                    if self.is_tracking() and self.should_stop_tracking(current_time):
                        logger.info(
                            f"Tracking session timeout for object {self.current_obj_id}"
                        )
                        self.stop_tracking()

                    # Wait for next update with timeout
                    try:
                        update = self.update_queue.get_nowait()
                    except Empty:
                        continue

                    if self.shutdown_event.is_set():
                        break

                    # Handle new object ID or start new tracking session if none active
                    if not self.is_tracking() or self.current_obj_id != update.obj_id:
                        self.start_new_tracking_session(update)

                    # Process update if we're still within tracking window
                    if self.is_tracking() and not self.should_stop_tracking(
                        current_time
                    ):
                        value = self.update_lens(update.z)
                        lens_update_time = time.time()

                        self.current_csv_writer.writerow(
                            [
                                update.trigger_time,
                                update.msg_receive_time,
                                update.frame,
                                lens_update_time,
                                update.z,
                                value,
                            ]
                        )
                        self.current_csv_file.flush()

                except Exception as e:
                    logger.error(f"Error in lens control: {e}")
                    if self.shutdown_event.is_set():
                        break

        finally:
            logger.info("Shutting down LensController")
            self.cleanup()

    def is_tracking(self) -> bool:
        """Check if we're currently tracking an object."""
        return self.current_obj_id is not None and self.tracking_start_time is not None

    def should_stop_tracking(self, current_time: float) -> bool:
        """Check if we should stop tracking based on elapsed time."""
        if not self.is_tracking():
            return False
        elapsed_time = current_time - self.tracking_start_time
        return elapsed_time >= self.tracking_duration

    def start_new_tracking_session(self, update: UpdateMessage):
        """Start tracking a new object."""
        logger.info(f"Starting new tracking session for object {update.obj_id}")

        # Close existing CSV file if any
        if self.current_csv_file:
            self.current_csv_file.close()

        # Create new CSV file for this object
        self.current_csv_writer, self.current_csv_file = create_csv_writer(
            self.video_folder_path, update.obj_id, update.frame
        )

        # Update tracking state
        self.current_obj_id = update.obj_id
        self.tracking_start_time = time.time()
        logger.info(
            f"Tracking started at {self.tracking_start_time}, will track for {self.tracking_duration} seconds"
        )

    def stop_tracking(self):
        """Stop tracking the current object and clean up."""
        if self.current_obj_id:
            logger.info(f"Stopping tracking session for object {self.current_obj_id}")
            elapsed_time = time.time() - self.tracking_start_time
            logger.info(f"Tracking session lasted {elapsed_time:.2f} seconds")

        if self.current_csv_file:
            self.current_csv_file.close()
            self.current_csv_file = None
            self.current_csv_writer = None

        self.current_obj_id = None
        self.tracking_start_time = None

    def update_lens(self, z: float) -> float:
        """Update lens position and return the set value."""
        value = float(self.calibration.get_dpt(z))
        if self.mode == "current":
            self.lens_driver.set_current(value)
        else:
            self.lens_driver.set_diopter(value)
        logger.debug(f"Updated lens to {self.mode}={value} for z={z}")
        return value

    def cleanup(self):
        """Clean up resources"""
        try:
            if self.is_tracking():
                self.stop_tracking()

            if hasattr(self, "lens_driver") and self.lens_driver:
                self.lens_driver.close()

        except Exception as e:
            logger.error(f"Error during LensController cleanup: {e}")


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
    # Load config and setup calibration
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)
    validate_config(config)
    calibration = setup_lens_calibration(interp_file)

    # Create communication queues and shutdown event
    trigger_queue = Queue()
    update_queue = Queue()
    shutdown_event = Event()

    # Initialize thread objects
    trigger_processor = TriggerProcessor(config, trigger_queue, shutdown_event)
    braid_processor = BraidStreamProcessor(
        config, trigger_queue, update_queue, shutdown_event
    )
    lens_controller = LensController(
        lens_port,
        calibration,
        update_queue,
        mode,
        debug,
        video_folder_path,
        shutdown_event,
    )

    threads = [trigger_processor, braid_processor, lens_controller]

    # Start all threads
    logger.info("Starting all threads...")
    for thread in threads:
        thread.start()

    try:
        # Wait for keyboard interrupt
        while True:
            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("Shutdown signal received, stopping all threads...")
        shutdown_event.set()

        # Give threads time to cleanup
        time.sleep(0.5)

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=2.0)
            if thread.is_alive():
                logger.warning(
                    f"Thread {thread.__class__.__name__} did not shut down cleanly"
                )

    finally:
        logger.info("All threads stopped, exiting...")


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
