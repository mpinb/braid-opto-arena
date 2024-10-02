import aiohttp
import asyncio
import yaml
import numpy as np
import json
import argparse
import logging
from typing import Dict, Tuple, Callable
from devices.lens_driver import LensDriver
import time
import matplotlib.pyplot as plt
import pandas as pd

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class TrackedObject:
    def __init__(self, obj_id: int, x: float, y: float, z: float, timestamp: float):
        self.obj_id = obj_id
        self.x = x
        self.y = y
        self.z = z
        self.last_update = timestamp
        self.birth_time = timestamp

    def update(self, x: float, y: float, z: float, timestamp: float):
        self.x = x
        self.y = y
        self.z = z
        self.last_update = timestamp


def load_tracking_zone(zone_file: str) -> Dict[str, Tuple[float, float]]:
    with open(zone_file, "r") as file:
        config = yaml.safe_load(file)

    # Extract box parameters from the trigger section
    box = config["trigger"]["box"]

    # Expand the zone by 0.01 in all dimensions
    return {
        "x": (box["x"][0] - 0.05, box["x"][1] + 0.05),
        "y": (box["y"][0] - 0.05, box["y"][1] + 0.05),
        "z": (box["z"][0] - 0.05, box["z"][1] + 0.05),
    }


# def load_z_to_diopter_map(map_file: str) -> Callable[[float], float]:
#     data = np.loadtxt(map_file, delimiter=",", skiprows=1)
#     if data.shape[0] < 2:
#         raise ValueError("CSV file must contain at least two data points")

#     z_values, dpt_values = data[:, 0], data[:, 1]

#     if len(z_values) == 2:
#         # Create a simple linear interpolation function for exactly two points
#         def interpolate(z: float) -> float:
#             return np.interp(z, z_values, dpt_values)
#     else:
#         # Create a linear regression function for more than two points
#         slope, intercept = np.polyfit(z_values, dpt_values, 1)

#         def interpolate(z: float) -> float:
#             return slope * z + intercept

#     fig = plt.figure()
#     plt.scatter(z_values, dpt_values, color="red", label="Data points")
#     n = 100
#     z_interp = np.linspace(min(z_values), max(z_values), n)
#     dpt_interp = [interpolate(z) for z in z_interp]
#     plt.plot(z_interp, dpt_interp, color="blue", label="Linear regression")
#     plt.xlabel("Z value")
#     plt.ylabel("Diopter")
#     plt.legend()
#     fig.savefig("z_to_diopter_map.png")
#     plt.close(fig)

#     return interpolate


def load_z_to_diopter_map(map_file: str):
    data = pd.read_csv(map_file)
    return data


def interpolate_dpt_from_z(map_data, z):
    return np.interp(z, map_data["z"], map_data["dpt"])


DATA_PREFIX = b"data: "


async def process_event_stream(url: str, queue: asyncio.Queue):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, headers={"Accept": "text/event-stream"}
        ) as response:
            buffer = b""
            async for chunk in response.content.iter_any():
                buffer += chunk
                while b"\n\n" in buffer:
                    message, buffer = buffer.split(b"\n\n", 1)
                    for line in message.split(b"\n"):
                        if line.startswith(DATA_PREFIX):
                            data = json.loads(line[len(DATA_PREFIX) :])
                            await queue.put(data)


async def track_objects(
    queue: asyncio.Queue,
    lens_driver: LensDriver,
    tracking_zone: Dict[str, Tuple[float, float]],
    map_data,
):
    tracked_objects = {}
    current_tracked_id = None
    last_update_time = 0

    while True:
        data = await queue.get()

        if "msg" in data:
            if "Update" in data["msg"] or "Birth" in data["msg"]:
                update_dict = data["msg"].get("Update") or data["msg"].get("Birth")
                obj_id = update_dict["obj_id"]
                x, y, z = update_dict["x"], update_dict["y"], update_dict["z"]
                timestamp = time.time()

                if obj_id in tracked_objects:
                    tracked_objects[obj_id].update(x, y, z, timestamp)
                else:
                    tracked_objects[obj_id] = TrackedObject(obj_id, x, y, z, timestamp)

                in_zone = (
                    tracking_zone["x"][0] <= x <= tracking_zone["x"][1]
                    and tracking_zone["y"][0] <= y <= tracking_zone["y"][1]
                    and tracking_zone["z"][0] <= z <= tracking_zone["z"][1]
                )

                if in_zone:
                    if current_tracked_id is None or obj_id == current_tracked_id:
                        current_tracked_id = obj_id
                        if (
                            timestamp - last_update_time >= 0.01
                        ):  # 10ms minimum update interval
                            diopter = interpolate_dpt_from_z(map_data, z)
                            lens_driver.set_diopter(diopter)
                            last_update_time = timestamp
                            logger.debug(
                                f"z={z}, diopter={diopter} (reported {lens_driver.get_diopter()})"
                            )
                elif obj_id == current_tracked_id:
                    current_tracked_id = None
                    logger.debug(f"Object {obj_id} left tracking zone")

            elif "Death" in data["msg"]:
                obj_id = data["msg"]["Death"]
                if obj_id in tracked_objects:
                    del tracked_objects[obj_id]
                    if obj_id == current_tracked_id:
                        current_tracked_id = None
                        logger.debug(f"Tracked object {obj_id} disappeared")

        queue.task_done()


async def run_tracking(
    braid_url: str, lens_port: str, zone_file: str, map_file: str, debug: bool = False
):
    if debug:
        logger.setLevel(logging.DEBUG)

    tracking_zone = load_tracking_zone(zone_file)
    try:
        map_data = load_z_to_diopter_map(map_file)
    except ValueError as e:
        logger.error(f"Error loading z to diopter map: {e}")
        return

    lens_driver = LensDriver(lens_port, debug=debug)
    lens_driver.set_mode("focal_power")

    queue = asyncio.Queue()

    try:
        event_stream_task = asyncio.create_task(
            process_event_stream(braid_url + "events", queue)
        )
        tracking_task = asyncio.create_task(
            track_objects(queue, lens_driver, tracking_zone, map_data)
        )

        await asyncio.gather(event_stream_task, tracking_task)
    except asyncio.CancelledError:
        logger.info("Tracking stopped")
    finally:
        lens_driver.disconnect()


def main():
    parser = argparse.ArgumentParser(description="3D Object Tracking and Lens Control")
    parser.add_argument(
        "--braid_url",
        help="URL for the braid server",
        default="http://127.0.0.1:8397/",
    )
    parser.add_argument(
        "--lens_port", help="Port for the lens controller", default="/dev/optotune_ld"
    )
    parser.add_argument(
        "--zone-file",
        default="/home/buchsbaum/src/braid-opto-arena/config.yaml",
        help="YAML file defining the tracking zone",
    )
    parser.add_argument(
        "--map-file",
        default="/home/buchsbaum/liquid_lens_calibration_20241002.csv",
        help="CSV file mapping Z values to diopter values",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    asyncio.run(
        run_tracking(
            args.braid_url, args.lens_port, args.zone_file, args.map_file, args.debug
        )
    )


if __name__ == "__main__":
    main()
