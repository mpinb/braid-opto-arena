import argparse
import json
import logging
import signal
import pandas as pd
import toml
from messages import Subscriber
from opto import Opto
from scipy.interpolate import interp1d
from utils.log_config import setup_logging

# Setup logging
setup_logging(level="DEBUG")
logger = logging.getLogger(__name__)


# Function to handle SIGINT (Ctrl+C) and SIGTERM
def signal_handler(signum, frame):
    raise SystemExit


# Set the handler for SIGINT and SIGTERM to the signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Load data from params file
margins = 0.01
PARAMS = toml.load("../params.toml")
XMIN = PARAMS["trigger_params"]["xmin"] - margins
XMAX = PARAMS["trigger_params"]["xmax"] + margins
YMIN = PARAMS["trigger_params"]["ymin"] - margins
YMAX = PARAMS["trigger_params"]["ymax"] + margins
ZMIN = PARAMS["trigger_params"]["zmin"]
ZMAX = PARAMS["trigger_params"]["zmax"]


class LiquidLens:
    def __init__(
        self,
        device_address: str,
        sub_port: int,
        handshake_port: int,
        debug: bool = False,
    ):
        self.sub_port = sub_port
        self.handshake_port = handshake_port
        self.device_address = device_address
        self.debug = debug
        self.current_tracked_object = None
        self.setup()

    def setup(self):
        self._setup_zmq()
        self._setup_calibration()
        self._setup_device()

    def _setup_device(self):
        """Setup the liquid lens controller."""
        logger.debug(f"Connecting to liquid lens controller at {self.device_address}")
        self.device = Opto(port=self.device_address)
        self.device.connect()
        self.device.current(0)

    def _setup_calibration(self):
        """Setup the calibration for the liquid lens controller."""
        logger.debug("Loading calibration data from ~/calibration_array.csv")
        calibration = pd.read_csv("~/calibration_array.csv")
        self.interp_current = interp1d(
            calibration["braid_position"], calibration["current"]
        )

    def _setup_zmq(self):
        """Setup the ZMQ subscriber."""
        self.subscriber = Subscriber(self.sub_port, self.handshake_port)

    def is_within_predefined_zone(self, data):
        x, y, z = data["x"], data["y"], data["z"]
        return XMIN <= x <= XMAX and YMIN <= y <= YMAX and ZMIN <= z <= ZMAX

    def run(self):
        try:
            while True:
                message = self.subscriber.receive()
                if message is None:
                    continue

                # Check if message is the "kill" command
                if message == "kill":
                    logger.info("Received kill message. Exiting...")
                    break

                try:
                    # Try to parse message as JSON
                    data = json.loads(message)
                    logger.debug(f"Received JSON data: {data}")
                except json.JSONDecodeError:
                    # Handle message as a simple string
                    logger.debug(f"Can't parse message: {message}")
                    continue

                if self.current_tracked_object is None:
                    if self.is_within_predefined_zone(data):
                        logger.info(f"Tracking object {data['obj_id']}")
                        self.current_tracked_object = data["obj_id"]
                        self.update_lens(data["z"])
                else:
                    if data.get("obj_id") == self.current_tracked_object:
                        if self.is_within_predefined_zone(data):
                            self.update_lens(data["z"])
                        else:
                            logger.info(
                                f"Object {self.current_tracked_object} left the tracking zone."
                            )
                            self.current_tracked_object = None
        except SystemExit:
            logger.info("Exiting due to signal.")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
        finally:
            self.close()

    def update_lens(self, z):
        current = self.interp_current(z)
        self.device.current(current)
        logger.debug(f"Set current to {current} for z={z}")

    def close(self):
        """Close the subscriber and the liquid lens controller."""
        logger.info("Closing device and subscriber.")
        self.device.close(soft_close=True)
        self.subscriber.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--device_address",
        type=str,
        default="/dev/ttyACM0",
        help="The address of the liquid lens controller",
    )
    parser.add_argument("--sub_port", type=int, default=5556)
    parser.add_argument("--handshake_port", type=int, default=5557)
    parser.add_argument("--debug", action="store_true", default=False)
    args = parser.parse_args()

    lens = LiquidLens(
        args.device_address, args.sub_port, args.handshake_port, args.debug
    )

    if args.debug:
        logger.info("Debug mode enabled. Waiting for user input.")
    else:
        logger.info("Starting liquid lens controller.")
        lens.run()
