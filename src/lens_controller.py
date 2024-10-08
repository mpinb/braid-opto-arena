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

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class InterpolatedLookupTable:
    def __init__(self, z_values: np.ndarray, dpt_values: np.ndarray, num_points: int = 10000):
        self.z_min = z_values.min()
        self.z_max = z_values.max()
        self.z_range = self.z_max - self.z_min
        
        dense_z = np.linspace(self.z_min, self.z_max, num_points)
        self.dense_dpt = np.interp(dense_z, z_values, dpt_values)
        
        self.num_points = num_points

    def lookup(self, z: float) -> float:
        if z <= self.z_min:
            return self.dense_dpt[0]
        elif z >= self.z_max:
            return self.dense_dpt[-1]
        else:
            idx = int((z - self.z_min) / self.z_range * (self.num_points - 1))
            return self.dense_dpt[idx]

def create_lookup_table(csv_file: str, num_points: int = 10000) -> InterpolatedLookupTable:
    data = pd.read_csv(csv_file)
    z_values = data["z"].values
    dpt_values = data["dpt"].values
    return InterpolatedLookupTable(z_values, dpt_values, num_points)

def update_lens_position(
    lens_driver: LensDriver, z: float, lookup_table: InterpolatedLookupTable
) -> float:
    diopter = lookup_table.lookup(z)
    lens_driver.set_diopter(diopter)
    return diopter

def run_tracking(
    braid_url: str,
    lens_port: str,
    config_file: str,
    interp_file: str,
    debug: bool,
    standalone: bool
) -> None:
    # Load config
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    # Create the interpolation function
    lookup_table = create_lookup_table(interp_file)

    # Initialize BraidProxy if in standalone mode
    braid_proxy = None
    if standalone:
        try:
            braid_proxy = BraidProxy(
                base_url=config["braid"]["url"],
                event_port=config["braid"]["event_port"],
                control_port=config["braid"]["control_port"],
                zmq_pub_port=config["zmq"]["braid_pub_port"]
            )
        except Exception as e:
            logger.error(f"Failed to initialize braid proxy: {e}")
            return

    # Connect to trigger subscriber
    try:
        trigger_subscriber = Subscriber(
            address="127.0.0.1",
            port=config["zmq"]["trigger_pub_port"],
            topics="trigger"
        )
        trigger_subscriber.initialize()
    except Exception as e:
        logger.error(f"Failed to initialize trigger subscriber: {e}")
        return

    # Connect to braid event subscriber
    try:
        braid_subscriber = Subscriber(
            address="127.0.0.1",
            port=config["zmq"]["braid_pub_port"],
            topics="braid_event"
        )
        braid_subscriber.initialize()
    except Exception as e:
        logger.error(f"Failed to initialize braid subscriber: {e}")
        return

    # Initialize lens driver
    try:
        lens_driver = LensDriver(port=lens_port, debug=debug)
        lens_driver.set_mode("focal_power")
    except Exception as e:
        logger.error(f"Failed to initialize lens driver: {e}")
        return

    lens_update_duration = 3

    # Flag to signal threads to stop
    stop_event = threading.Event()

    def process_braid_events(obj_id: str, end_time: float):
        while time.time() < end_time and not stop_event.is_set():
            topic, message = braid_subscriber.receive(timeout=0.1)
            if topic is None:
                continue

            event = json.loads(message)
            msg_dict = event.get("msg", {})

            if "Update" in msg_dict and msg_dict["Update"]["obj_id"] == obj_id:
                z = msg_dict["Update"]["z"]
                received_time = event.get("received_time", time.time())
                
                update_start_time = time.time()
                dpt = update_lens_position(lens_driver, z, lookup_table)
                update_end_time = time.time()
                
                latency_us = (update_end_time - received_time) * 1e6
                update_duration_us = (update_end_time - update_start_time) * 1e6
                
                logger.info(f"Object {obj_id}: z={z:.2f}, diopter={dpt:.2f}")
                logger.debug(f"Latency: {latency_us:.2f} µs, Update duration: {update_duration_us:.2f} µs")

        lens_driver.ramp_to_zero()
        logger.info(f"Finished tracking object {obj_id}. Resetting lens position.")

    def process_triggers():
        while not stop_event.is_set():
            topic, message = trigger_subscriber.receive(timeout=1.0)
            if topic is None:
                continue
            
            if topic == "trigger":
                if message == "kill":
                    logger.info("Received kill message. Shutting down...")
                    stop_event.set()
                    break
                
                trigger_info = json.loads(message)
                obj_id = trigger_info["obj_id"]
                logger.info(f"Received trigger for object {obj_id}")
                
                end_time = time.time() + lens_update_duration
                process_braid_events(obj_id, end_time)

    # Start the trigger processing in a separate thread
    trigger_thread = threading.Thread(target=process_triggers, daemon=True)
    trigger_thread.start()

    if standalone:
        # Start the BraidProxy event processing in a separate thread
        braid_thread = threading.Thread(target=braid_proxy.process_events, daemon=True)
        braid_thread.start()

    try:
        # Keep the main thread alive
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received. Shutting down...")
        stop_event.set()
    finally:
        stop_event.set()  # Ensure all threads know to stop
        trigger_thread.join(timeout=5)  # Wait for trigger thread to finish
        if standalone and braid_proxy:
            braid_thread.join(timeout=5)  # Wait for braid thread to finish if in standalone mode
        
        trigger_subscriber.close()
        braid_subscriber.close()
        lens_driver.disconnect()
        if braid_proxy:
            braid_proxy.close()
        
        logger.info("Shutdown complete.")

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
    parser.add_argument("--standalone", action="store_true", help="Run in standalone mode with own BraidProxy")
    args = parser.parse_args()

    run_tracking(
        args.braid_url,
        args.lens_port,
        args.config_file,
        args.interp_file,
        args.debug,
        args.standalone
    )

if __name__ == "__main__":
    main()