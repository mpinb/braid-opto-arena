import logging
import multiprocessing as mp
import time
from queue import Empty, Queue
from threading import Barrier, Event

from .cameras import TriggeredBaslerCam
from .ThreadClass import ThreadClass


class CamerasManager(ThreadClass):
    """_summary_

    Args:
        ThreadClass (_type_): _description_
    """

    def __init__(
        self,
        queue: Queue,
        kill_event: Event,
        barrier: Barrier,
        params: dict,
        *args,
        **kwargs,
    ) -> None:
        """_summary_

        Args:
            queue (Queue): _description_
            kill_event (Event): _description_
            barrier (Barrier): _description_
            params (dict): _description_
        """
        super(CamerasManager, self).__init__(
            queue, barrier, kill_event, params, *args, **kwargs
        )

        # Threading stuff
        self.cameras = params["highspeed"]["cameras"]

    def run(self):
        """_summary_"""
        # Set mp.Event for the cameras
        self.cameras_trigger_event = mp.Event()

        # Start all cameras
        self.start_cameras()

        # Wait for all processes/threads to start
        logging.debug("Reached barrier.")
        self.barrier.wait()

        # Start main loop
        logging.info("Starting main loop.")
        while not self.kill_event.is_set():
            # Get data from queue
            data = self.queue.get()

            # Send the data to each camera queue
            for cam_name, cam_queue in self.mp_cameras_queues.items():
                logging.debug(f"Putting data in queue {cam_name}.")
                cam_queue.put(data)

        # Kill all cameras
        self.mp_cameras_kill_event.set()

    def start_cameras(self):
        """_summary_"""
        # Create dictionary to store camera proceesses
        self.mp_cameras = {}

        # And camera queues
        self.mp_cameras_queues = {}

        # Initialize kill event and barrier for cameras using mp
        self.mp_cameras_kill_event = mp.Event()
        self.mp_cameras_barrier = mp.Barrier(len(self.cameras))

        # Start all cameras
        for cam_name, cam_serial in self.cameras.items():
            logging.info(f"Starting camera {cam_name} with serial {cam_serial}.")
            # Create new queue for each camera
            self.mp_cameras_queues[cam_serial] = Queue()

            # Create a new process for each camera
            self.mp_cameras[cam_serial] = TriggeredBaslerCam(
                serial=cam_serial,
                camera_params=self.params["highspeed"]["parameters"],
                barrier=self.mp_cameras_barrier,
                kill_event=self.mp_cameras_kill_event,
                incoming_data_queue=self.mp_cameras_queues[cam_serial],
            ).start()
            logging.debug(f"Created camera process for {cam_name}.")
            # Give the camera enough time to initialize
            time.sleep(3)


if __name__ == "__main__":
    c = CamerasManager(
        queue=Queue(),
        kill_event=Event(),
        barrier=Barrier(1),
        params={"highspeed": {"cameras": {"cam1": "1234"}}},
        name="test",
        daemon=True,
    )
