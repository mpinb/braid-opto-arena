from opto import Opto
import argparse
from messages import Subscriber
import logging
import numpy as np


def position_to_current(position):
    # implement a function that converts the position to a current
    pass


class LiquidLens(Opto):
    def __init__(
        self,
        port: str,
        sub_port: int,
        handshake_port: int,
    ):
        super().__init__(port)

        self.sub_port = sub_port
        self.handshake_port = handshake_port
        self.setup_zmq()

    def setup_zmq(self):
        """
        Setup the subscriber and handshake ports for the liquid lens controller.
        """
        self.subscriber = Subscriber(self.sub_port, self.handshake_port)
        self.subscriber.handshake()
        logging.info("Handshake complete")
        self.subscriber.subscribe("lens")
        logging.info("Subscribed to messages")

    def run(self):
        """
        Run the liquid lens controller. The controller will receive messages from the subscriber
        and adjust the current of the liquid lens based on the z position.
        """
        prev_z = 0
        curr_z = 0
        while True:
            message = self.subscriber.receive()
            if message == "kill":
                break
            elif message is not None:
                curr_z = message["z"]
                if np.abs(curr_z - prev_z) >= 0.01:
                    self.current(position_to_current(curr_z))
                    prev_z = curr_z
            else:
                pass

        self.close()

    def close(self):
        """
        Close the subscriber and the liquid lens controller."""
        self.subscriber.close()
        super().close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "device address",
        nargs="1",
        default="/dev/ttyACM0",
        help="The address of the liquid lens controller",
    )
    parser.add_argument("--sub_port", type=int, default=5556)
    parser.add_argument("--handshake_port", type=int, default=5557)
    args = parser.parse_args()

    lens = LiquidLens(args.device_address, args.sub_port, args.handshake_port)
    lens.run()
