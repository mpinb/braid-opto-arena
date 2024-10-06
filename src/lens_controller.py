import asyncio
import aiohttp
import yaml
import numpy as np
import json
import argparse
import logging
from typing import Dict, Tuple
from devices.lens_driver import LensDriver
import pandas as pd
from collections import deque
from heapq import heappush, heappop
from functools import lru_cache

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
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
    box = config["trigger"]["box"]
    return {
        "x": (box["x"][0] - 0.025, box["x"][1] + 0.025),
        "y": (box["y"][0] - 0.025, box["y"][1] + 0.025),
        "z": (box["z"][0], box["z"][1]),
    }

def load_z_to_diopter_map(map_file: str):
    return pd.read_csv(map_file)

@lru_cache(maxsize=1000)
def interpolate_dpt_from_z(z):
    return np.interp(z, map_data["z"], map_data["dpt"])

class ObjectTracker:
    def __init__(self, lens_driver: LensDriver, tracking_zone: Dict[str, Tuple[float, float]]):
        self.lens_driver = lens_driver
        self.tracking_zone = tracking_zone
        self.tracked_objects = {}
        self.current_tracked_id = None
        self.last_update_time = 0
        self.objects_in_zone = set()
        self.priority_queue = []
        self.map_data = map_data
        self.interpolate_dpt_from_z = lru_cache(maxsize=1000)(self._interpolate_dpt_from_z)

    def _interpolate_dpt_from_z(self, z):
            return np.interp(z, self.map_data["z"], self.map_data["dpt"])

    async def process_data(self, data):
        timestamp = asyncio.get_event_loop().time()

        if "msg" in data:
            if "Update" in data["msg"] or "Birth" in data["msg"]:
                update_dict = data["msg"].get("Update") or data["msg"].get("Birth")
                obj_id = update_dict["obj_id"]
                x, y, z = update_dict["x"], update_dict["y"], update_dict["z"]

                if obj_id in self.tracked_objects:
                    self.tracked_objects[obj_id].update(x, y, z, timestamp)
                else:
                    self.tracked_objects[obj_id] = TrackedObject(obj_id, x, y, z, timestamp)

                in_zone = self.is_in_zone(x, y, z)

                if in_zone and obj_id not in self.objects_in_zone:
                    self.objects_in_zone.add(obj_id)
                    heappush(self.priority_queue, (timestamp, obj_id))
                elif not in_zone and obj_id in self.objects_in_zone:
                    self.objects_in_zone.remove(obj_id)

                if in_zone:
                    if self.current_tracked_id is None or obj_id == self.current_tracked_id:
                        self.current_tracked_id = obj_id
                        if timestamp - self.last_update_time >= 0.01:
                            await self.adjust_lens_focus(z, obj_id)
                            self.last_update_time = timestamp
                elif obj_id == self.current_tracked_id:
                    self.current_tracked_id = await self.find_next_object_to_track()
                    if self.current_tracked_id is not None:
                        new_obj = self.tracked_objects[self.current_tracked_id]
                        await self.adjust_lens_focus(new_obj.z, self.current_tracked_id)
                        self.last_update_time = timestamp

            elif "Death" in data["msg"]:
                obj_id = data["msg"]["Death"]
                if obj_id in self.tracked_objects:
                    del self.tracked_objects[obj_id]
                    self.objects_in_zone.discard(obj_id)
                    if obj_id == self.current_tracked_id:
                        self.current_tracked_id = await self.find_next_object_to_track()
                        if self.current_tracked_id is not None:
                            new_obj = self.tracked_objects[self.current_tracked_id]
                            await self.adjust_lens_focus(new_obj.z, self.current_tracked_id)
                            self.last_update_time = timestamp

    def is_in_zone(self, x: float, y: float, z: float) -> bool:
        return (
            self.tracking_zone["x"][0] <= x <= self.tracking_zone["x"][1]
            and self.tracking_zone["y"][0] <= y <= self.tracking_zone["y"][1]
            and self.tracking_zone["z"][0] <= z <= self.tracking_zone["z"][1]
        )

    async def find_next_object_to_track(self) -> int | None:
        while self.priority_queue:
            _, obj_id = heappop(self.priority_queue)
            if obj_id in self.objects_in_zone:
                return obj_id
        return None

    async def adjust_lens_focus(self, z: float, obj_id: int):
        diopter = interpolate_dpt_from_z(z)
        await self.lens_driver.set_diopter(diopter)
        reported_diopter = await self.lens_driver.get_diopter()

        if abs(diopter - reported_diopter) > 0.1:
            logger.warning(f"Focus adjustment discrepancy for object {obj_id}: z={z}, requested diopter={diopter:.2f}, reported diopter={reported_diopter:.2f}")

async def event_stream_processor(url: str, queue: asyncio.Queue):
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(url, headers={"Accept": "text/event-stream"}) as response:
                    async for line in response.content:
                        if line.startswith(b"data: "):
                            data = json.loads(line[6:])
                            await queue.put(data)
            except aiohttp.ClientError as e:
                logger.error(f"Error in event stream: {e}")
                await asyncio.sleep(0.1)

async def run_tracking(braid_url: str, lens_port: str, zone_file: str, map_file: str, debug: bool = False):
    if debug:
        logger.setLevel(logging.DEBUG)

    global map_data
    tracking_zone = load_tracking_zone(zone_file)
    map_data = load_z_to_diopter_map(map_file)

    lens_driver = LensDriver(lens_port, debug=debug)
    await lens_driver.set_mode("focal_power")

    data_queue = asyncio.Queue()
    object_tracker = ObjectTracker(lens_driver, tracking_zone)

    event_stream_task = asyncio.create_task(event_stream_processor(braid_url + "events", data_queue))

    try:
        while True:
            data = await data_queue.get()
            await object_tracker.process_data(data)
    except asyncio.CancelledError:
        logger.info("Stopping tracking...")
    finally:
        event_stream_task.cancel()
        await lens_driver.disconnect()

def main():
    parser = argparse.ArgumentParser(description="3D Object Tracking and Lens Control")
    parser.add_argument("--braid_url", help="URL for the braid server", default="http://127.0.0.1:8397/")
    parser.add_argument("--lens_port", help="Port for the lens controller", default="/dev/optotune_ld")
    parser.add_argument("--zone-file", default="/home/buchsbaum/src/braid-opto-arena/config.yaml", help="YAML file defining the tracking zone")
    parser.add_argument("--map-file", default="/home/buchsbaum/liquid_lens_calibration_20241002.csv", help="CSV file mapping Z values to diopter values")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    asyncio.run(run_tracking(args.braid_url, args.lens_port, args.zone_file, args.map_file, args.debug))

if __name__ == "__main__":
    main()