import asyncio
import json
import random
import math
from aiohttp import web


class FruitFlySimulator:
    def __init__(self):
        self.current_obj_id = 0
        self.current_frame = 0
        self.fly_data = None
        self.arena_radius = 0.25
        self.arena_height = 0.3
        self.arena_center = [0, 0, 0.15]

    def generate_new_fly(self):
        self.current_obj_id += 1
        x = random.uniform(-self.arena_radius, self.arena_radius)
        y = random.uniform(-self.arena_radius, self.arena_radius)
        z = random.uniform(0, self.arena_height)
        return {
            "obj_id": self.current_obj_id,
            "frame": self.current_frame,
            "x": x + self.arena_center[0],
            "y": y + self.arena_center[1],
            "z": z + self.arena_center[2] - self.arena_height / 2,
            "vx": random.uniform(-0.1, 0.1),
            "vy": random.uniform(-0.1, 0.1),
            "vz": random.uniform(-0.1, 0.1),
        }

    def update_fly_position(self):
        if self.fly_data is None:
            return None

        # Update position
        self.fly_data["x"] += self.fly_data["vx"]
        self.fly_data["y"] += self.fly_data["vy"]
        self.fly_data["z"] += self.fly_data["vz"]

        # Check boundaries and adjust if necessary
        x = self.fly_data["x"] - self.arena_center[0]
        y = self.fly_data["y"] - self.arena_center[1]
        z = self.fly_data["z"] - (self.arena_center[2] - self.arena_height / 2)

        if x**2 + y**2 > self.arena_radius**2 or z < 0 or z > self.arena_height:
            # If out of bounds, reverse direction with some randomness
            self.fly_data["vx"] = -self.fly_data["vx"] * random.uniform(0.8, 1.2)
            self.fly_data["vy"] = -self.fly_data["vy"] * random.uniform(0.8, 1.2)
            self.fly_data["vz"] = -self.fly_data["vz"] * random.uniform(0.8, 1.2)

        # Add some randomness to velocity
        self.fly_data["vx"] += random.uniform(-0.01, 0.01)
        self.fly_data["vy"] += random.uniform(-0.01, 0.01)
        self.fly_data["vz"] += random.uniform(-0.01, 0.01)

        # Limit velocity
        speed = math.sqrt(
            self.fly_data["vx"] ** 2
            + self.fly_data["vy"] ** 2
            + self.fly_data["vz"] ** 2
        )
        if speed > 0.2:
            self.fly_data["vx"] *= 0.2 / speed
            self.fly_data["vy"] *= 0.2 / speed
            self.fly_data["vz"] *= 0.2 / speed

        self.fly_data["frame"] = self.current_frame
        return self.fly_data

    async def simulate(self):
        while True:
            self.current_frame += 1
            if (
                self.fly_data is None or random.random() < 0.001
            ):  # Chance to generate new fly
                if self.fly_data is not None:
                    yield self.create_event(
                        "Death", {"obj_id": self.fly_data["obj_id"]}
                    )
                self.fly_data = self.generate_new_fly()
                yield self.create_event("Birth", self.fly_data)
            else:
                updated_data = self.update_fly_position()
                if updated_data:
                    yield self.create_event("Update", updated_data)
            await asyncio.sleep(0.01)  # 100 FPS

    def create_event(self, event_type, data):
        return {
            "v": 3,
            "msg": {event_type: data},
            "latency": 0.0,
            "synced_frame": self.current_frame,
            "trigger_timestamp": 0.0,
        }


async def events(request):
    simulator = FruitFlySimulator()
    response = web.StreamResponse()
    response.headers["Content-Type"] = "text/event-stream"
    await response.prepare(request)

    try:
        async for event in simulator.simulate():
            event_data = json.dumps(event)
            try:
                await response.write(
                    f"event: braid\ndata: {event_data}\n\n".encode("utf-8")
                )
            except (ConnectionResetError, asyncio.CancelledError):
                # Client disconnected or server is shutting down
                break
    except asyncio.CancelledError:
        # Server is shutting down
        pass
    finally:
        try:
            await response.write_eof()
        except ConnectionResetError:
            # Ignore connection reset error on write_eof
            pass

    return response


async def root(request):
    return web.Response(text="Fruit Fly Simulator Server")


app = web.Application()
app.router.add_get("/", root)
app.router.add_get("/events", events)


async def on_shutdown(app):
    for ws in set(app["websockets"]):
        await ws.close(code=1001, message="Server shutdown")
    app["websockets"].clear()


async def start_background_tasks(app):
    app["websockets"] = set()


async def cleanup_background_tasks(app):
    pass


def main():
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host="127.0.0.1", port=8397)


if __name__ == "__main__":
    main()
