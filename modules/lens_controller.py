import argparse
import csv
import json
import os
import time

import numpy as np
import pandas as pd
import requests
import toml
from opto import Opto
from scipy.interpolate import interp1d
from utils.log_config import setup_logging

# Setup logging
logger = setup_logging(logger_name="LensController", level="INFO", color="cyan")
LENS_RESPONSE_TIME = 20  # ms
LENS_RESPONSE_TIME /= 1e3  # seconds


class LiquidLens:
    def __init__(
        self,
        device_address: str,
        braidz_url: str,
        params_file: str,
        save_folder: str = "",
        margins: int = 0.05,
    ):
        # Initialize the liquid lens controller
        self.device_address = device_address

        # Initialize the Braidz proxy
        self.braidz_url = braidz_url
        self.session = None
        self.r = None
        self.events_url = None

        # Initialize the parameters
        self.params_file = params_file

        # Initialize the tracking parameters
        self.tracking_start_time = time.time()
        self.tcall = time.time()
        self.margins = margins
        self.current_tracked_object = None

        # Initialize the liquid lens controller
        self.save_folder = save_folder
        self.csv_file = None
        self.csv_writer = None

        # Initialize the setup
        self.setup()

    def setup(self):
        self._read_params()
        self._setup_braidz_proxy()
        self._setup_calibration()
        self._setup_device()
        self._setup_csv_writer()

    def _read_params(self):
        """Read the parameters from the params file."""
        logger.debug(f"Reading parameters from {self.params_file}")
        with open(self.params_file, "r") as f:
            params = toml.load(f)
            self.xmin = params["trigger_params"]["xmin"] - self.margins
            self.xmax = params["trigger_params"]["xmax"] + self.margins
            self.ymin = params["trigger_params"]["ymin"] - self.margins
            self.ymax = params["trigger_params"]["ymax"] + self.margins
            self.zmin = params["trigger_params"]["zmin"] - self.margins
            self.zmax = params["trigger_params"]["zmax"] + self.margins

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
            kind="linear",
            fill_value="extrapolate",
        )

    def _setup_braidz_proxy(self):
        self.session = requests.Session()
        r = self.session.get(self.braidz_url)
        assert (
            r.status_code == requests.codes.ok
        ), f"Failed to connect to {self.braidz_url}"
        self.events_url = self.braidz_url + "events"
        self.r = self.session.get(
            self.events_url,
            stream=True,
            headers={"Accept": "text/event-stream"},
        )

    def _parse_chunk(self, chunk):
        lines = chunk.strip().split("\n")
        assert len(lines) == 2
        assert lines[0] == "event: braid"
        assert lines[1].startswith("data: ")
        buf = lines[1][len("data: ") :]
        data = json.loads(buf)
        return data

    def _setup_csv_writer(
        self,
        header=["msg_time", "update_time", "current", "z"],
    ):
        # Check if the file exists
        file_path = os.path.join(self.save_folder, "lens_controller.csv")
        file_exists = os.path.isfile(file_path)
        self.csv_file = open(file_path, "a+", newline="")

        self.csv_file.seek(0)  # Move to the start of the file
        reader = csv.reader(self.csv_file)
        rows = list(reader)

        # If the file does not exist or is empty, write the header
        if not file_exists or not rows:
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(header)
            return

        # If the file exists but has no header (first row is empty), write the header
        if not rows[0]:
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow(header)
            return

        # If the file exists and has a header, just set the writer
        self.csv_writer = csv.writer(self.csv_file)

    def _write_row(self, row):
        if self.csv_writer:
            self.csv_writer.writerow(row)

    def is_within_predefined_zone(self, data):
        # check if data contains all required keys
        if data is None:
            return False
        else:
            x, y, z = data["x"], data["y"], data["z"]
            return (
                self.xmin <= x <= self.xmax
                and self.ymin <= y <= self.ymax
                and self.zmin <= z <= self.zmax
            )

    def run(self):
        runtime = []
        try:
            for chunk in self.r.iter_content(chunk_size=None, decode_unicode=True):
                incoming_full = self._parse_chunk(chunk)
                self.tcall = time.time()
                try:
                    incoming = incoming_full["msg"]
                except KeyError:
                    continue

                data = None
                incoming_object = None
                msg_type = None

                # message parser
                for msg_type in ["Birth", "Update", "Death"]:
                    if msg_type in incoming:
                        if msg_type == "Death":
                            data = None
                            incoming_object = incoming[msg_type]
                        else:
                            data = incoming[msg_type]
                            incoming_object = data["obj_id"]
                        break

                # check if object is within zone
                in_zone = self.is_within_predefined_zone(data)

                # this is the main logic
                if self.current_tracked_object is None:
                    if in_zone:
                        self.start_tracking(incoming_object, data)

                elif self.current_tracked_object == incoming_object:
                    if msg_type == "Death" or not in_zone:
                        self.stop_tracking()
                    elif in_zone:
                        self.update_lens(data["z"])

                runtime.append(time.time() - self.tcall)

        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt. Exiting...")
            logger.debug(f"Average runtime: {np.mean(runtime)*1e3:.3f} ms")
        finally:
            self.close()

    def start_tracking(self, incoming_object, data):
        logger.info(f"Started tracking object {incoming_object}")
        self.tracking_start_time = time.time()
        self.current_tracked_object = incoming_object
        self.update_lens(data["z"])

    def update_lens(self, z):
        if time.time() - self.tcall > LENS_RESPONSE_TIME:
            current = self.interp_current(z)
            self.device.current(current)

            logger.debug(
                f"Current: {current:.0f} for z: {z:.3f} ({(time.time() - self.tcall):.6f} seconds)"
            )
            self._write_row([time.time(), self.tcall, current, z])

    def stop_tracking(self):
        self.device.current(0)
        self.current_tracked_object = None
        logger.debug(
            f"Stopped tracking object {self.current_tracked_object} after {(time.time() - self.tracking_start_time):.2f} seconds"
        )

    def close(self):
        """Close the liquid lens controller."""
        logger.info("Closing device.")
        self.device.close(soft_close=True)
        self.csv_file.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--device_address",
        type=str,
        default="/dev/optotune_ld",
        help="The address of the liquid lens controller",
    )
    parser.add_argument("--braidz_url", type=str, default="http://10.40.80.6:8397/")
    parser.add_argument(
        "--params_file",
        type=str,
        default="/home/buchsbaum/src/BraidTrigger/params.toml",
    )
    parser.add_argument("--save_folder", type=str, default="")
    args = parser.parse_args()

    lens = LiquidLens(
        device_address=args.device_address,
        braidz_url=args.braidz_url,
        params_file=args.params_file,
        save_folder=args.save_folder,
    )

    logger.info("Starting liquid lens controller.")
    lens.run()
