import argparse
import logging
import time
import yaml
import numpy as np
import json
from typing import Dict, Any
from devices.lens_driver import LensDriver
from messages import Subscriber, Publisher
from braid_proxy import BraidProxy
import pandas as pd
import threading
from sklearn.linear_model import LinearRegression
import os
import zmq


# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class LinearRegressionLookup:
    def __init__(self, csv_file: str):
        if not os.path.exists(csv_file):
            raise FileNotFoundError(f"CSV file not found: {csv_file}")

        try:
            data = pd.read_csv(csv_file)
        except pd.errors.EmptyDataError:
            raise ValueError(f"The CSV file {csv_file} is empty.")
        except pd.errors.ParserError:
            raise ValueError(
                f"Unable to parse the CSV file {csv_file}. Please check the file format."
            )

        if "z" not in data.columns or "dpt" not in data.columns:
            raise ValueError(
                f"The CSV file {csv_file} must contain 'z' and 'dpt' columns."
            )
        z_values = data["z"].values
        dpt_values = data["dpt"].values

        if len(z_values) < 2:
            raise ValueError(
                f"The CSV file {csv_file} must contain at least two data points."
            )

        self.z_min = z_values.min()
        self.z_max = z_values.max()
        # Fit linear regression model
        self.model = LinearRegression()
        self.model.fit(z_values.reshape(-1, 1), dpt_values)
        self.slope = self.model.coef_[0]
        self.intercept = self.model.intercept_

    def lookup(self, z: float) -> float:
        # Predict using the linear regression model
        return self.slope * z + self.intercept


class LensController:
    def __init__(
        self,
        config: Dict[str, Any],
        lens_port: str,
        interp_file: str,
        debug: bool,
        standalone: bool,
    ):
        self.config = config
        self.lens_port = lens_port
        self.debug = debug
        self.standalone = standalone
        self.lookup_table = LinearRegressionLookup(interp_file)
        self.lens_driver = None
        self.braid_proxy = None
        self.trigger_subscriber = None
        self.braid_subscriber = None
        self.stop_event = threading.Event()
        self.lens_update_duration = 3
        self.refresh_rate = 100  # Hz

    def initialize(self):
        if self.standalone:
            self.initialize_braid_proxy()

        self.initialize_subscribers()
        self.initialize_lens_driver()

    def initialize_braid_proxy(self):
        try:
            self.braid_proxy = BraidProxy(
                base_url=self.config["braid"]["url"],
                event_port=self.config["braid"]["event_port"],
                control_port=self.config["braid"]["control_port"],
                zmq_pub_port=self.config["zmq"]["braid_pub_port"],
            )

        except Exception as e:
            logger.error(f"Failed to initialize braid proxy: {e}")

            raise

    def initialize_subscribers(self):
        try:
            self.trigger_subscriber = Subscriber(
                address="127.0.0.1",
                port=self.config["zmq"]["trigger_pub_port"],
                topics="trigger",
            )
            self.trigger_subscriber.initialize()

            self.braid_subscriber = Subscriber(
                address="127.0.0.1",
                port=self.config["zmq"]["braid_pub_port"],
                topics="braid_event",
            )
            self.braid_subscriber.initialize()

        except Exception as e:
            logger.error(f"Failed to initialize subscribers: {e}")

            raise

    def initialize_lens_driver(self):
        try:
            self.lens_driver = LensDriver(port=self.lens_port, debug=self.debug)
            self.lens_driver.set_mode("focal_power")

        except Exception as e:
            logger.error(f"Failed to initialize lens driver: {e}")
            raise

    def update_lens_position(self, z: float) -> float:
        diopter = self.lookup_table.lookup(z)

        self.lens_driver.set_diopter(diopter)

        return diopter

    def process_braid_events(self, obj_id: str, end_time: float):
        while time.time() < end_time and not self.stop_event.is_set():
            result = self.braid_subscriber.receive(blocking=False)

            if result is None:
                continue

            topic, message = result

            try:
                event = json.loads(message)

            except json.JSONDecodeError:
                logger.error(f"Failed to parse JSON message: {message}")

                continue

            msg_dict = event.get("msg", {})

            if "Update" in msg_dict and msg_dict["Update"]["obj_id"] == obj_id:
                z = msg_dict["Update"]["z"]

                received_time = event.get("received_time", time.time())

                update_start_time = time.time()

                try:
                    dpt = self.update_lens_position(z)

                except Exception as e:
                    logger.error(f"Failed to update lens position: {e}")

                    continue

                update_end_time = time.time()

                latency_us = (update_end_time - received_time) * 1e6

                update_duration_us = (update_end_time - update_start_time) * 1e6

                logger.info(f"Object {obj_id}: z={z:.2f}, diopter={dpt:.2f}")

                logger.debug(
                    f"Latency: {latency_us:.2f} µs, Update duration: {update_duration_us:.2f} µs"
                )

        self.lens_driver.ramp_to_zero()

        logger.info(f"Finished tracking object {obj_id}. Resetting lens position.")

    def process_triggers(self):
        while not self.stop_event.is_set():
            result = self.trigger_subscriber.receive(blocking=False)

            if result is None:
                continue

            topic, message = result

            if topic == "trigger":
                if message == "kill":
                    logger.info("Received kill message. Shutting down...")
                    self.stop_event.set()
                    break
                try:
                    trigger_info = json.loads(message)

                except json.JSONDecodeError:
                    logger.error(f"Failed to parse JSON message: {message}")
                    continue

                obj_id = trigger_info.get("obj_id")

                if obj_id is None:
                    logger.error(f"Missing obj_id in trigger message: {trigger_info}")

                    continue

                logger.info(f"Received trigger for object {obj_id}")
                end_time = time.time() + self.lens_update_duration
                self.process_braid_events(obj_id, end_time)

    def run(self):
        self.initialize()

        trigger_thread = threading.Thread(target=self.process_triggers, daemon=True)
        trigger_thread.start()

        if self.standalone:
            braid_thread = threading.Thread(
                target=self.braid_proxy.process_events, daemon=True
            )
            braid_thread.start()

        try:
            while not self.stop_event.is_set():
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Shutting down...")
            self.stop_event.set()

        finally:
            self.stop_event.set()
            trigger_thread.join(timeout=5)

            if self.standalone and self.braid_proxy:
                braid_thread.join(timeout=5)

            self.cleanup()

    def cleanup(self):
        if self.trigger_subscriber:
            self.trigger_subscriber.close()

        if self.braid_subscriber:
            self.braid_subscriber.close()

        if self.lens_driver:
            self.lens_driver.disconnect()

        if self.braid_proxy:
            self.braid_proxy.close()

        logger.info("Shutdown complete.")


def load_config(config_file: str) -> Dict[str, Any]:
    try:
        with open(config_file, "r") as f:
            return yaml.safe_load(f)

    except FileNotFoundError:
        logger.error(f"Config file not found: {config_file}")
        raise

    except yaml.YAMLError as e:
        logger.error(f"Error parsing config file: {e}")
        raise


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
        default="/home/buchsbaum/liquid_lens_calibration_20241002.csv",
        help="CSV file mapping Z values to diopter values",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Run in standalone mode with own BraidProxy",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config_file)
        lens_controller = LensController(
            config=config,
            lens_port=args.lens_port,
            interp_file=args.interp_file,
            debug=args.debug,
            standalone=args.standalone,
        )

        lens_controller.run()

    except Exception as e:
        logger.error(f"An error occurred: {e}")

        exit(1)


if __name__ == "__main__":
    main()
