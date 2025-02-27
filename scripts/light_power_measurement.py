#!/usr/bin/env python3

import argparse
import requests
import json
import socket
import os
import threading
import time
from collections import defaultdict
import numpy as np
import pyvisa
from queue import Queue
from datetime import datetime


class PowerMeter:
    def __init__(self):
        self.rm = pyvisa.ResourceManager()
        self.device = None
        self.sampling_queue = Queue()
        self._running = False
        diameter_mm = 9.5
        self.sensor_area_mm2 = np.pi * (diameter_mm / 2) ** 2

    def connect(self, resource_name):
        """Connect to the PM100D device and configure for power density measurements."""
        try:
            self.device = self.rm.open_resource(resource_name)

            # 1. Configure wavelength for 625nm
            self.device.write("SENS:CORR:WAV 625")

            # 2. Configure for power measurements in Watts
            self.device.write("SENS:POW:UNIT W")

            # 3. Set beam diameter to 50mm
            self.device.write("SENS:CORR:BEAMdiameter 50.0")

            # 4. Set averaging to reduce noise (300 samples, ~100ms)
            self.device.write("SENS:AVER:COUNT 300")

            # 5. Enable auto-ranging for best resolution
            self.device.write("SENS:POW:RANG:AUTO 1")

            # 6. Verify settings
            wavelength = float(self.device.query("SENS:CORR:WAV?"))
            beam_diam = float(self.device.query("SENS:CORR:BEAM?"))
            power_unit = self.device.query("SENS:POW:UNIT?").strip()

            print(f"Power meter configured:")
            print(f"- Wavelength: {wavelength} nm")
            print(f"- Beam diameter: {beam_diam} mm")
            print(f"- Power unit: {power_unit}")

            # 7. Perform initial zero adjustment
            print("Performing zero adjustment...")
            self.device.write("SENS:CORR:COLL:ZERO")
            while int(self.device.query("SENS:CORR:COLL:ZERO:STAT?")) == 1:
                time.sleep(0.1)

            # 8. Check all parameters after setup
            self.check_measurement_params()

            return True
        except Exception as e:
            print(f"Error connecting to power meter: {e}")
            return False

    def check_measurement_params(self):
        """Check current measurement parameters."""
        try:
            power_range = float(self.device.query("POW:RANG?"))
            averaging = int(self.device.query("AVER:COUN?"))
            zero_magnitude = float(self.device.query("SENS:CORR:COLL:ZERO:MAGN?"))

            print("\nMeasurement parameters:")
            print(f"- Current power range: {power_range * 1000:.2f} mW")
            print(f"- Averaging count: {averaging}")
            print(f"- Zero offset: {zero_magnitude * 1e6:.1f} µW")

            return True
        except Exception as e:
            print(f"Error checking parameters: {e}")
            return False

    def start_sampling(self):
        """Start the power measurement sampling thread."""
        self._running = True
        self.sampling_thread = threading.Thread(target=self._sample_power)
        self.sampling_thread.daemon = True
        self.sampling_thread.start()

    def stop_sampling(self):
        """Stop the power measurement sampling."""
        self._running = False
        if hasattr(self, "sampling_thread"):
            self.sampling_thread.join()

    def _sample_power(self):
        """Continuously sample power measurements."""
        while self._running:
            try:
                # First get raw power in W
                power_w = float(self.device.query("MEAS:POW?"))

                power_density_uw_mm2 = (power_w * 1e6) / self.sensor_area_mm2

                timestamp = time.time()
                self.sampling_queue.put((timestamp, power_w, power_density_uw_mm2))
            except Exception as e:
                print(f"Error reading power: {e}")
            time.sleep(0.1)  # Reduced sampling rate for debugging

    def cleanup(self):
        """Clean up resources."""
        if self.device:
            self.device.close()
        self.rm.close()


class BraidTracker:
    def __init__(self, braid_url):
        self.braid_url = braid_url
        self.session = requests.session()
        self.current_frame_data = defaultdict(dict)  # frame -> obj_id -> position
        self.center_positions = []  # List of (frame, center_position) tuples

    def calculate_center(self, positions):
        """Calculate the center point of the LEDs."""
        if len(positions) != 4:
            return None

        positions = np.array(positions)
        # Check if points form a reasonable square/rectangle
        distances = np.linalg.norm(positions - positions.mean(axis=0), axis=1)
        if np.std(distances) > 20:  # Adjust threshold as needed
            print("Warning: LED positions may be incorrect")

        return positions.mean(axis=0)

    def process_update(self, data):
        try:
            update_dict = data["msg"]["Update"]
            obj_id = update_dict.get("obj_id")
            frame = update_dict.get("frame")  # Get frame number
            position = [update_dict["x"], update_dict["y"], update_dict["z"]]

            if frame is None:
                print("Warning: No frame number in update data")
                return None

            self.current_frame_data[frame][obj_id] = position

            # If we have all 4 LEDs for this frame, calculate center
            if len(self.current_frame_data[frame]) == 4:
                positions = list(self.current_frame_data[frame].values())
                center = self.calculate_center(positions)
                if center is not None:
                    self.center_positions.append((frame, center))
                    # print(f"Frame {frame}: Center position: {center}")
                # Clean up processed frame
                del self.current_frame_data[frame]

                # Clean up old frames (keep only last 100 frames in memory)
                old_frames = [
                    f for f in self.current_frame_data.keys() if f < frame - 100
                ]
                for f in old_frames:
                    del self.current_frame_data[f]

        except (KeyError, ValueError) as e:
            print(f"Error processing update: {e}")
            return None


class DataLogger:
    def __init__(self, output_file):
        self.output_file = output_file
        self.file = open(output_file, "w")
        # Write header
        self.file.write("frame,timestamp,x,y,z,power_W,power_density_uw_mm2\n")
        self.last_power_timestamp = 0

    def log_data(self, frame, timestamp, position, power, power_density):
        """Log frame, timestamp, position and power data."""

        self.file.write(
            f"{frame},{timestamp},{position[0]},{position[1]},{position[2]},{power},{power_density}\n"
        )
        self.file.flush()
        self.last_power_timestamp = timestamp

    def cleanup(self):
        """Close the output file."""
        self.file.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--braid-url", default="http://127.0.0.1:8397/", help="URL of braid server"
    )
    parser.add_argument(
        "--power-meter",
        default="USB0::4883::32888::P0043115::0::INSTR",
        help="VISA resource name for power meter",
    )
    parser.add_argument(
        "--output",
        default=f"tracking_power_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        help="Output file for logged data",
    )
    args = parser.parse_args()

    # Initialize components
    power_meter = PowerMeter()
    braid_tracker = BraidTracker(args.braid_url)
    data_logger = DataLogger(args.output)

    try:
        # Connect to power meter
        if not power_meter.connect(args.power_meter):
            raise Exception("Failed to connect to power meter")

        # Start power sampling
        power_meter.start_sampling()

        # Connect to braid stream
        events_url = args.braid_url + "events"
        r = braid_tracker.session.get(
            events_url,
            stream=True,
            headers={"Accept": "text/event-stream"},
        )

        print(f"Starting data collection... (writing to {args.output})")
        print("Press Ctrl+C to stop")

        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            # Process braid events
            data = parse_chunk(chunk)
            braid_tracker.process_update(data)

            # If we have new position data
            if braid_tracker.center_positions:
                frame, position = braid_tracker.center_positions[-1]

                # Get the closest power reading
                if not power_meter.sampling_queue.empty():
                    timestamp, power, power_density = power_meter.sampling_queue.get()
                    data_logger.log_data(
                        frame, timestamp, position, power, power_density
                    )

    except KeyboardInterrupt:
        print("\nStopping data collection...")
    except Exception as e:
        print(f"\nError during data collection: {e}")
    finally:
        power_meter.stop_sampling()
        power_meter.cleanup()
        data_logger.cleanup()


DATA_PREFIX = "data: "


def parse_chunk(chunk):
    lines = chunk.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "event: braid"
    assert lines[1].startswith(DATA_PREFIX)
    buf = lines[1][len(DATA_PREFIX) :]
    data = json.loads(buf)
    return data


if __name__ == "__main__":
    main()
