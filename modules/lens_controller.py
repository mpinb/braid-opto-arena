from opto import Opto
import argparse
from messages import Subscriber
import logging
import numpy as np
import time
import pandas as pd
from scipy.interpolate import interp1d
import json
import signal


# Function to ignore SIGINT (Ctrl+C)
def ignore_signal(signum, frame):
    print("SIGINT signal ignored")


# Set the handler for SIGINT to the ignore function
signal.signal(signal.SIGINT, ignore_signal)

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class LiquidLens(Opto):
    def __init__(
        self, port: str, sub_port: int, handshake_port: int, debug: bool = False
    ):
        super().__init__(port)
        self.sub_port = sub_port
        self.handshake_port = handshake_port
        self.debug = debug
        self.setup_zmq()
        self.setup_calibration()
        self.connect()

    def setup_calibration(self):
        """Setup the calibration for the liquid lens controller."""
        calibration = pd.read_csv("~/calibration_array.csv")
        self.interp_current = interp1d(
            calibration["braid_position"], calibration["current"]
        )

    def setup_zmq(self):
        """Setup the subscriber and handshake ports for the liquid lens controller."""
        self.subscriber = Subscriber(self.sub_port, self.handshake_port)
        self.subscriber.handshake()
        logging.info("lens_controller.py - Handshake complete")
        self.subscriber.subscribe("lens")
        logging.info("lens_controller.py - Subscribed to messages")

    def run(self):
        """Controls the lens based on received ZMQ messages, adjusting the lens position with a variable update rate."""
        logging.info("Starting liquid lens control loop")

        prev_z = 0
        # max_dt = 1.0  # Maximum dt when object is at or outside the boundary
        while True:
            try:
                tcall = time.time()
                message = self.subscriber.receive()
                if message == "kill":
                    break
                elif message is not None:
                    message = json.loads(message)
                    x, y, z = message["x"], message["y"], message["z"]
                    dt = self.calculate_dt(x, y)
                    if self.is_in_activation_area(x, y, z) and self.is_time_to_update(
                        z, prev_z, tcall, dt
                    ):
                        self.current(self.interp_current(z))
                        logging.info(
                            f"Position: {z}; Current: {self.interp_current(z)}"
                        )
                        prev_z = z
            except Exception as e:
                logging.error(f"Error in run loop: {e}")
            time.sleep(0.01)

    def calculate_dt(self, x, y):
        """Calculates the dynamic time step based on the distance from the center."""
        radius = np.sqrt(x**2 + y**2)
        max_radius = 0.20  # Half the diameter
        if radius > max_radius:
            return 1.0  # Effectively stops updates when outside the defined cylinder
        # Linear interpolation between fast update rate at center to no update at boundary
        return (1 - (radius / max_radius)) * 0.1 + 0.01  # Adjust these values as needed

    def is_in_activation_area(self, x, y, z):
        """Checks if the current position is within the defined activation area."""
        return np.sqrt(x**2 + y**2) < 0.2 and 0.1 < z < 0.3

    def is_time_to_update(self, z, prev_z, tcall, dt):
        """Determines if enough time has passed to warrant an update to the lens position."""
        return np.abs(z - prev_z) >= 0.01  # and time.time() - tcall > dt

    def close(self):
        """Close the subscriber and the liquid lens controller."""
        self.subscriber.close()
        super().close()


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
        logging.info("Debug mode enabled. Waiting for user input.")
    else:
        logging.info("Starting liquid lens controller.")
        lens.run()
