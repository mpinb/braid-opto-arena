import argparse
import logging
import time
import yaml
import numpy as np
import json
import asyncio
from typing import Dict, Any
from functools import lru_cache
from devices.lens_driver import LensDriver
from messages import Subscriber  # Assume we have an async version of Subscriber
from braid_proxy import BraidProxy
from async_braid_proxy import AsyncBraidProxy
import pandas as pd
from sklearn.linear_model import LinearRegression

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def run_tracking(
    braid_url: str, lens_port: str, config_file: str, interp_file: str, debug: bool
) -> None:
    # Load config
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    # Load interpolation data
    interp_data = pd.read_csv(interp_file)
    z_values, dpt_values = interp_data["z"].values, interp_data["dpt"].values
    model = LinearRegression().fit(z_values.reshape(-1, 1), dpt_values)
    slope = model.coef_[0]
    intercept = model.intercept_

    # Initialize AsyncBraidProxy
    async with AsyncBraidProxy(
        base_url=config["braid"]["url"],
        event_port=config["braid"]["event_port"],
        control_port=config["braid"]["control_port"],
    ) as braid_proxy:
        # Connect to subscriber
        subscriber = Subscriber(
            address="127.0.0.1", port=config["zmq"]["port"], topics="trigger"
        )
        subscriber.initialize()

        # Initialize lens driver
        lens_driver = LensDriver(port=lens_port, debug=debug)
        lens_driver.set_mode("focal_power")

        lens_update_duration = 3

        try:
            while True:
                # Receive message
                topic, message = subscriber.receive()
                start_time = time.time()

                # Process message
                if message == "kill":
                    raise KeyboardInterrupt

                trigger_info = json.loads(message)
                obj_id = trigger_info["obj_id"]

                # Initialize a flag to check if we've updated the lens at least once
                lens_updated = False

                # Update lens position
                async for event in braid_proxy.iter_events():
                    if event is None:
                        continue
                    else:
                        msg_dict = event["msg"]
                        if "Update" in msg_dict:
                            msg_dict = msg_dict["Update"]
                            if msg_dict["obj_id"] == obj_id:
                                z = msg_dict["z"]
                                lens_driver.set_diopter(slope * z + intercept)
                                lens_updated = True

                    if time.time() - start_time > lens_update_duration:
                        break

                # If we didn't update the lens (no matching events), log a warning
                if not lens_updated:
                    logger.warning(f"No matching events found for object {obj_id}")

                # Reset lens position
                lens_driver.ramp_to_zero()

        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await subscriber.close()
            lens_driver.disconnect()


async def main() -> None:
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
    args = parser.parse_args()

    await run_tracking(
        args.braid_url, args.lens_port, args.config_file, args.interp_file, args.debug
    )


if __name__ == "__main__":
    asyncio.run(main())
