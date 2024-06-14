from opto import Opto
import argparse
from messages import Subscriber
import logging
import numpy as np
import pandas as pd
from scipy.interpolate import interp1d
import json
import signal
from utils.log_config import setup_logging

# Setup logging
setup_logging(level="DEBUG")
logger = logging.getLogger(__name__)


# Function to ignore SIGINT (Ctrl+C)
def ignore_signal(signum, frame):
    pass


# Set the handler for SIGINT to the ignore function
signal.signal(signal.SIGINT, ignore_signal)


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
        """Setup the subscriber and handshake ports for the liquid lens controller."""
        logger.debug(f"Setting up subscriber on port {self.sub_port}")
        self.subscriber = Subscriber(self.sub_port, self.handshake_port)
        self.subscriber.handshake()
        logger.info("lens_controller.py - Handshake complete")
        self.subscriber.subscribe()
        logger.info("lens_controller.py - Subscribed to messages")

    def run(self):
        """Controls the lens based on received ZMQ messages, adjusting the lens position with a variable update rate."""
        logger.info("Starting liquid lens control loop")
        while True:
            topic, message = self.subscriber.receive(block=True)
            if message == "kill":
                break

            message = json.loads(message)
            if topic == "trigger":
                logger.debug("Received first ")
                obj_id_to_track = message["obj_id"]

            if message["obj_id"] == obj_id_to_track:
                current = self.interp_current(message["z"])
                self.current(current)
                logger.debug(f"Position: {message["z"]}; Current: {message["z"]}")

        self.close()

    def is_in_activation_area(self, x, y, z):
        """Checks if the current position is within the defined activation area."""
        return np.sqrt(x**2 + y**2) < 0.2 and 0.1 < z < 0.3

    def close(self):
        """Close the subscriber and the liquid lens controller."""
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
