import argparse
import json
import signal
import pandas as pd
import toml
from messages import Subscriber
from opto import Opto
from scipy.interpolate import interp1d
from utils.log_config import setup_logging
import time

# Setup logging
logger = setup_logging(logger_name="LensController", level="INFO", color="cyan")


# Function to handle SIGINT (Ctrl+C) and SIGTERM
def signal_handler(signum, frame):
    raise SystemExit


# Set the handler for SIGINT and SIGTERM to the signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Load data from params file
margins = 0.01
PARAMS = toml.load("/home/buchsbaum/src/BraidTrigger/params.toml")
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
        logger.debug("Handshaking with the publisher.")
        self.subscriber.handshake()
        logger.debug("Subscribing to 'lens' topic.")
        self.subscriber.subscribe("lens")
        logger.info("Finished zmq setup")

    def is_within_predefined_zone(self, data):
        x, y, z = data["x"], data["y"], data["z"]
        return XMIN <= x <= XMAX and YMIN <= y <= YMAX and ZMIN <= z <= ZMAX

    def run(self):
        try:
            while True:
                topic, message = self.subscriber.receive()
                if message is None:
                    continue

                # Check if message is the "kill" command
                if message == "kill":
                    logger.info("Received kill message. Exiting...")
                    break

                try:
                    # Try to parse message as JSON
                    msg = json.loads(message)
                    logger.debug(f"Received JSON data: {msg}")
                except json.JSONDecodeError:
                    # Handle message as a simple string
                    logger.warning(f"Can't parse message: {msg}")
                    continue

                # first parse the incoming message to see if it is a Birth, Update, or Death message
                incoming_object = None
                for msg_type in ["Birth", "Update", "Death"]:
                    if msg_type in msg:
                        data = msg[msg_type]
                        incoming_object = data["obj_id"]
                        break

                # if it's none of the above, continue
                # this shouldn't actually every happen
                if incoming_object is None:
                    logger.warning(f"Invalid message: {msg}")
                    continue

                # checf if no object is currently being tracked
                if self.current_tracked_object is None:
                    # if the object is within the predefined zone, start tracking it
                    if self.is_within_predefined_zone(data):
                        logger.info(f"Tracking object {incoming_object}")
                        tracking_start_time = time.time()

                        # set the current tracked object to the incoming object
                        self.current_tracked_object = incoming_object

                        # and update lens if z is present
                        if "z" in data:
                            self.update_lens(data["z"])
                else:
                    # if there is already a tracked object
                    # check if the incoming object is the same as the currently tracked object
                    if incoming_object == self.current_tracked_object:
                        # if the data contains a z value, update the lens
                        if "z" in data and self.is_within_predefined_zone(data):
                            self.update_lens(data["z"])
                        # otherwise, the object has either (a) left the trigger zone or (b) died
                        # so stop tracking
                        else:
                            logger.info(
                                f"Object {self.current_tracked_object} left the tracking zone after {time.time() - tracking_start_time} seconds."
                            )
                            self.current_tracked_object = None

        except SystemExit:
            logger.info("Exiting due to signal.")
        except Exception as e:
            logger.warning(f"Unexpected error: {e}")
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
