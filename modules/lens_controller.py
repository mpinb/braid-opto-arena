import argparse
import json
import signal
import time

import pandas as pd
import toml
from messages import Subscriber
from opto import Opto
from scipy.interpolate import interp1d
from utils.log_config import setup_logging

# Setup logging
logger = setup_logging(logger_name="LensController", level="INFO", color="cyan")


# Function to handle SIGINT (Ctrl+C) and SIGTERM
def signal_handler(signum, frame):
    raise SystemExit


# Set the handler for SIGINT and SIGTERM to the signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Load data from params file
margins = 0.05
PARAMS = toml.load("/home/buchsbaum/src/BraidTrigger/params.toml")
XMIN = PARAMS["trigger_params"]["xmin"] - margins
XMAX = PARAMS["trigger_params"]["xmax"] + margins
YMIN = PARAMS["trigger_params"]["ymin"] - margins
YMAX = PARAMS["trigger_params"]["ymax"] + margins
ZMIN = PARAMS["trigger_params"]["zmin"] - margins
ZMAX = PARAMS["trigger_params"]["zmax"] + margins

TIME_THRESHOLD = 0.5


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
            calibration["braid_position"],
            calibration["current"],
            type="linear",
            fill_value="extrapolate",
        )

    def _setup_zmq(self):
        """Setup the ZMQ subscriber."""
        self.subscriber = Subscriber(self.sub_port, self.handshake_port)
        logger.debug("Handshaking with the publisher.")
        self.subscriber.handshake()
        logger.debug("Subscribing to 'lens' topic.")
        self.subscriber.subscribe("lens")
        logger.info("Finished zmq setup")

    def is_within_predefined_zone(self, data):
        # check if data contains all required keys
        if data is None:
            return False
        elif not all(key in data for key in ["x", "y", "z"]):
            return False
        else:
            x, y, z = data["x"], data["y"], data["z"]
            return XMIN <= x <= XMAX and YMIN <= y <= YMAX and ZMIN <= z <= ZMAX

    def run(self):
        try:
            while True:
                tcall = time.time()
                topic, message = self.subscriber.receive()
                if message is None:
                    continue

                if message == "kill":
                    logger.info("Received kill message. Exiting...")
                    break

                try:
                    msg = json.loads(message)
                    # logger.debug(f"Received JSON data: {msg}")
                except json.JSONDecodeError:
                    logger.debug(f"Can't parse message: {message}")
                    continue

                # message parser
                # birth and update are treated the same
                if "Birth" in msg:
                    msg_type = "Birth"
                    data = msg[msg_type]
                    incoming_object = data["obj_id"]

                elif "Update" in msg:
                    msg_type = "Update"
                    data = msg[msg_type]
                    incoming_object = data["obj_id"]

                # howerver if it's a death message AND it's the same object, then we stop tracking
                # and continue with the main loop
                elif "Death" in msg:
                    msg_type = "Death"
                    incoming_object = msg[msg_type]
                    data = None

                else:
                    logger.debug(f"Invalid message: {msg}")
                    continue

                # this is the main logic
                if self.current_tracked_object is None:
                    if self.is_within_predefined_zone(data):
                        self.start_tracking(incoming_object, tcall)
                        # self.tracking_start_time = tcall
                        # self.current_tracked_object = incoming_object
                        # self.start_tracking(incoming_object, data)

                elif self.current_tracked_object == incoming_object:
                    if msg_type == "Death" or not self.is_within_predefined_zone(data):
                        self.stop_tracking()
                    elif tcall - self.tracking_start_time >= TIME_THRESHOLD:
                        self.update_lens(data["z"])

        except SystemExit:
            logger.info("Exiting due to signal.")
        finally:
            self.close()

    def start_tracking(self, incoming_object, tcall):
        logger.info(f"Tracking object {incoming_object}")
        self.current_tracked_object = incoming_object
        self.tracking_start_time = tcall

    def stop_tracking(self):
        logger.info(
            f"Object {self.current_tracked_object} left the tracking zone after {(time.time() - self.tracking_start_time):.2f} seconds."
        )
        self.device.current(0)
        self.current_tracked_object = None

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
