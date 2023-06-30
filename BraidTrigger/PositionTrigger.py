import logging
import time
from threading import Event, Barrier
from queue import Queue, Empty
from ThreadClass import ThreadClass


class PositionTrigger(ThreadClass):
    """_summary_

    Args:
        ThreadClass (_type_): _description_
    """

    def __init__(
        self,
        out_queues: list | Queue,
        queue: Queue,
        kill_event: Event,
        barrier: Barrier,
        params: dict,
        *args,
        **kwargs,
    ) -> None:
        """_summary_

        Args:
            out_queues (list | Queue): _description_
            queue (Queue): _description_
            kill_event (Event): _description_
            barrier (Barrier): _description_
            params (dict): _description_
        """
        super(PositionTrigger, self).__init__(
            queue, kill_event, barrier, params, *args, **kwargs
        )

        # Threading stuff
        self.out_queues = out_queues

        # Get trajectory parameters
        self.min_trajec_time = params["min_trajec_time"]
        self.refractory_time = params["refractory_time"]
        self.radius_min = params["radius_min"]
        self.zmin = params["zmin"]
        self.zmax = params["zmax"]

    def run(self):
        """_summary_"""
        # Tracking control stuff
        curr_obj_id = None
        obj_ids = []
        obj_birth_times = {}
        ntrig = 0

        # Wait for all processes/threads to start
        logging.debug("Reached barrier.")
        self.barrier.wait()

        # Set last trigger time as current
        last_trigger = time.time()
        logging.info("Starting main loop.")

        # Start the main loop
        while not self.kill_event.is_set():
            # Get current timestamp
            tcall = time.time()

            # Get data from queue
            try:
                data = self.queue.get(block=False, timeout=0.01)
            except Empty:
                continue

            # Check for birth event
            if "Birth" in data:
                logging.debug(f"Birth event: {data['Birth']}")
                cur_obj_id = data["Birth"]["obj_id"]
                obj_ids.append(cur_obj_id)
                obj_birth_times[cur_obj_id] = tcall
                continue

            # Check for update event
            if "Update" in data:
                logging.debug(f"Update event: {data['Update']}")
                curr_obj_id = data["Update"]["obj_id"]

                # If somehow we missed the "Birth" event, add it now
                if curr_obj_id not in obj_ids:
                    logging.debug(f"Adding birth event for Update event {curr_obj_id}")
                    obj_ids.append(curr_obj_id)
                    obj_birth_times[curr_obj_id] = tcall
                    continue

            # Check for death event
            if "Death" in data:
                logging.debug(f"Death event: {data['Death']}")
                curr_obj_id = data["Death"]
                if curr_obj_id in obj_ids:
                    obj_birth_times.pop(curr_obj_id)

            # Check for trajectory time
            if (tcall - obj_birth_times[curr_obj_id]) < self.min_trajec_time:
                logging.debug(f"Trajectory time for {curr_obj_id} too short.")
                continue

            # Check for refractory time from last trigger
            if tcall - last_trigger < self.refractory_time:
                logging.debug(f"Refractory time not met for obj {curr_obj_id}.")
                continue

            # Get positional data
            pos = data["Update"]
            radius = self._get_radius_fast(
                pos["x"], pos["y"], self.center_x, self.center_y
            )

            # Check for trigger conditions
            if radius <= self.radius and self.zmin <= pos["z"] <= self.zmax:
                # Set trigger counter and time
                ntrig += 1
                last_trigger = tcall

                # Set trigger event
                trigger_time = time.time()
                data["trigger_time"] = trigger_time

                # Send the data to the output queues
                for q in self.out_queues:
                    logging.debug(f"Sending data to queue {q}.")
                    data["queue_send_time"] = time.time()
                    q.put(data)

                logging.info(f"Triggered {ntrig} times.")

        logging.info("Main loop terminated.")

        while not self.queue.empty():
            logging.debug("Clearing queue.")
            self.queue.get()

    def _get_radius_fast(x, y, center_x, center_y):
        """_summary_

        Args:
            x (_type_): _description_
            y (_type_): _description_
            center_x (_type_): _description_
            center_y (_type_): _description_

        Returns:
            _type_: _description_
        """
        return ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
