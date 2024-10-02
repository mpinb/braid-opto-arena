import asyncio
import yaml
import csv
import requests
import json
import argparse
import logging
from typing import Dict, List, Tuple
from lens_controller import LensController

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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
    with open(zone_file, 'r') as file:
        config = yaml.safe_load(file)
    
    # Extract box parameters from the trigger section
    box = config['trigger']['box']
    
    # Expand the zone by 0.01 in all dimensions
    return {
        'x': (box['x'][0] - 0.025, box['x'][1] + 0.025),
        'y': (box['y'][0] - 0.025, box['y'][1] + 0.025),
        'z': (box['z'][0] - 0.025, box['z'][1] + 0.025)
    }

def load_z_to_diopter_map(map_file: str) -> List[Tuple[float, float]]:
    with open(map_file, 'r') as file:
        reader = csv.reader(file)
        next(reader)  # Skip header
        return [(float(row[0]), float(row[1])) for row in reader]

def interpolate_diopter(z: float, z_to_diopter_map: List[Tuple[float, float]]) -> float:
    for i in range(len(z_to_diopter_map) - 1):
        z1, d1 = z_to_diopter_map[i]
        z2, d2 = z_to_diopter_map[i + 1]
        if z1 <= z <= z2:
            return d1 + (d2 - d1) * (z - z1) / (z2 - z1)
    return z_to_diopter_map[-1][1]  # Return last diopter value if z is out of range

async def process_event_stream(url: str, queue: asyncio.Queue):
    async with requests.Session() as session:
        async with session.get(url, stream=True) as response:
            async for line in response.iter_lines():
                if line.startswith(b'data: '):
                    data = json.loads(line[6:])
                    await queue.put(data)

async def update_lens_focus(lens_controller: LensController, tracked_object: TrackedObject, z_to_diopter_map: List[Tuple[float, float]]):
    diopter = interpolate_diopter(tracked_object.z, z_to_diopter_map)
    await asyncio.to_thread(lens_controller.set_diopter, diopter)
    logger.debug(f"Lens focus updated: {diopter} diopters")

async def track_objects(queue: asyncio.Queue, lens_controller: LensController, tracking_zone: Dict[str, Tuple[float, float]], z_to_diopter_map: List[Tuple[float, float]]):
    tracked_objects = {}
    current_tracked_id = None
    last_update_time = 0

    while True:
        event = await queue.get()
        
        if 'msg' in event:
            if 'Birth' in event['msg']:
                data = event['msg']['Birth']
                obj_id = data['obj_id']
                x, y, z = data['x'], data['y'], data['z']
                timestamp = data['timestamps']
                
                tracked_objects[obj_id] = TrackedObject(obj_id, x, y, z, timestamp)
                logger.info(f"New object born: {obj_id}")

                in_zone = (tracking_zone['x'][0] <= x <= tracking_zone['x'][1] and
                           tracking_zone['y'][0] <= y <= tracking_zone['y'][1] and
                           tracking_zone['z'][0] <= z <= tracking_zone['z'][1])

                if in_zone and current_tracked_id is None:
                    current_tracked_id = obj_id
                    await update_lens_focus(lens_controller, tracked_objects[obj_id], z_to_diopter_map)
                    last_update_time = timestamp
                    logger.info(f"Started tracking object: {obj_id}")

            elif 'Update' in event['msg']:
                data = event['msg']['Update']
                obj_id = data['obj_id']
                x, y, z = data['x'], data['y'], data['z']
                timestamp = data['timestamps']

                if obj_id in tracked_objects:
                    tracked_objects[obj_id].update(x, y, z, timestamp)
                else:
                    # This shouldn't happen if Birth events are working correctly, but just in case
                    tracked_objects[obj_id] = TrackedObject(obj_id, x, y, z, timestamp)
                    logger.warning(f"Received Update for unknown object: {obj_id}")

                in_zone = (tracking_zone['x'][0] <= x <= tracking_zone['x'][1] and
                           tracking_zone['y'][0] <= y <= tracking_zone['y'][1] and
                           tracking_zone['z'][0] <= z <= tracking_zone['z'][1])

                if in_zone:
                    if current_tracked_id is None or obj_id == current_tracked_id:
                        current_tracked_id = obj_id
                        if timestamp - last_update_time >= 0.01:  # 10ms minimum update interval
                            await update_lens_focus(lens_controller, tracked_objects[obj_id], z_to_diopter_map)
                            last_update_time = timestamp
                elif obj_id == current_tracked_id:
                    current_tracked_id = None
                    logger.info(f"Object {obj_id} left tracking zone")

            elif 'Death' in event['msg']:
                obj_id = event['msg']['Death']
                if obj_id in tracked_objects:
                    del tracked_objects[obj_id]
                    if obj_id == current_tracked_id:
                        current_tracked_id = None
                        logger.info(f"Tracked object {obj_id} disappeared")

        queue.task_done()

async def run_tracking(braid_url: str, lens_port: str, zone_file: str, map_file: str, debug: bool = False):
    if debug:
        logger.setLevel(logging.DEBUG)

    tracking_zone = load_tracking_zone(zone_file)
    z_to_diopter_map = load_z_to_diopter_map(map_file)
    
    lens_controller = LensController(lens_port, debug=debug)
    lens_controller.set_mode("focal_power")
    
    queue = asyncio.Queue()
    
    event_stream_task = asyncio.create_task(process_event_stream(braid_url, queue))
    tracking_task = asyncio.create_task(track_objects(queue, lens_controller, tracking_zone, z_to_diopter_map))
    
    try:
        await asyncio.gather(event_stream_task, tracking_task)
    except asyncio.CancelledError:
        logger.info("Tracking stopped")
    finally:
        lens_controller.disconnect()

def main():
    parser = argparse.ArgumentParser(description="3D Object Tracking and Lens Control")
    parser.add_argument("braid_url", help="URL for the braid server", default="http://127.0.0.1:8397/")
    parser.add_argument("lens_port", help="Port for the lens controller", default="/dev/optotune_ld")
    parser.add_argument("--zone-file", default="tracking_zone.yaml", help="YAML file defining the tracking zone")
    parser.add_argument("--map-file", default="z_to_diopter.csv", help="CSV file mapping Z values to diopter values")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    asyncio.run(run_tracking(args.braid_url, args.lens_port, args.zone_file, args.map_file, args.debug))

if __name__ == "__main__":
    main()