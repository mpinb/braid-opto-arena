import logging
import multiprocessing as mp
import threading
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from queue import Queue
from typing import Any

from pypylon import pylon
from vidgear.gears import WriteGear


@dataclass
class DataPacket:
    frames: Iterable
    metadata: Mapping[str, Any]


class BaslerCam(mp.Process):
    def __init__(self, serial, *args, **kwargs):
        super().__init__(self, *args, **kwargs)

        # Get arguments
        self.serial = serial
        self.args = args
        self.kwargs = kwargs

        # Initialize camera
        self._initialize()
        self._set_camera_parameter()
        self._set_process_parameter()

    def _initialize(self):
        """
        Initialize the camera
        """

        # Initialize camera
        tlf = pylon.TlFactory.GetInstance()

        # Get device for serial number
        info = pylon.DeviceInfo()
        info.SetSerialNumber(self.serial)

        # start camera
        self.cam = tlf.CreateDevice(info)

    def _set_camera_parameter(self):
        """
        Set the camera parameters
        """

        # Set camera parameters
        self.open()

        # Loop over the parameters of the camera, and change them if they exist in the input parameters
        [
            setattr(self.cam, key, value)
            for key, value in self.kwargs.items()
            if key in dir(self.cam)
        ]
        # for key in dir(self.cam):
        #     if key in self.kwargs:
        #         setattr(self.cam, key, self.kwargs[key])

    def _set_process_parameter(self):
        """
        Set the process parameters
        (barriers, queues, events, etc)
        """

        # Set process parameters
        for key, value in self.kwargs.items():
            setattr(self, key, value)

    def run(self):
        """
        Main wrapper to start camera recording
        """

        # Start video writer thread
        self.queue = Queue()
        self.video_writer = threading.thread(target=self.threaded_video_writer).start()

        # If the camera is set to free run, start the camera in free run mode
        if self.run_type == "free_run":
            self.free_run()

        # If the camera is set to triggered run, start the camera in triggered run mode
        elif self.run_type == "triggered_run":
            if self._check_mp():
                self.triggered_run()

        # If the camera is set to something else, raise an error
        else:
            self.queue.put(None)
            raise ValueError("Invalid run type")

    def free_run(self):
        """
        Run the camera in free run mode, so we record until the user stops the program
        """

        # Initialize frames array
        frames = []

        # If there's a barrier, wait for it
        if hasattr(self, "barrier"):
            self.barrier.wait()

        # Start looping until keyboard interrupt
        try:
            while True:
                with self.cam.RetrieveResult(
                    self.exposure_time, pylon.TimeoutHandling_ThrowException
                ) as grabResult:
                    frames.append(grabResult.GetArray())

        # If there's a keyboard interrupt, put the frames into the queue
        except KeyboardInterrupt:
            self.queue.put(DataPacket(frames, self.metadata))
            pass

        # Stop the camera
        self.stop()

        # Close the camera
        self.close()

        # Put None into the queue to signal the video writer to stop
        self.queue.put(None)
        self.video_writer.join()

    def triggered_run(self):
        """
        Run the camera in pre-trigger mode. The camera continously saves frames into a circular buffer.
        When the trigger is set, record until there are n+m frames in the buffer, where n+m == fps*time
        """

        # Initialize frames deque
        frames = deque(maxlen=self.fps * self.time)
        frames_number = 0
        trigger_set = 0

        # If there's a barrier, wait for it
        if hasattr(self, "barrier"):
            self.barrier.wait()

        # Start looping until keyboard interrupt
        try:
            while True:
                # Check if trigger is set
                trigger = self.trigger.is_set()

                # Get frame from camera
                with self.cam.RetrieveResult(
                    self.exposure_time, pylon.TimeoutHandling_ThrowException
                ) as grabResult:
                    frames.append(grabResult.GetArray())

                # Check if trigger was set
                if trigger:
                    trigger_set = 1

                # If the trigger was set, increment the frame number
                if trigger_set:
                    frames_number += 1

                    # And if the frame number is greater than the fps*time
                    # put the frames into the queue, and reset the frame number
                    if frames_number >= self.fps * self.time:
                        self.queue.put(DataPacket(frames, self.metadata))
                        frames_number = 0
                        trigger_set = 0

        # If there's a keyboard interrupt, put None into the queue
        # to signal the video writer to stop
        except KeyboardInterrupt:
            logging.info("Keyboard interrupt")

        # Stop the camera
        self.stop()

        # Close the camera
        self.close()

        # Put None into the queue to signal the video writer to stop
        self.queue.put(None)
        self.video_writer.join()

    def threaded_video_writer(self):
        # Set output parameters
        output_params = {
            "-input_framerate": 25,
            "-vcodec": "h264_nvenc",
            "-preset": "fast",
            "-rc": "cbr_ld_hq",
            "-disable_force_termination": True,
        }

        # Loop, waiting for data packets to arrive to the video writer
        while True:
            # Get packet from queue
            packet = self.queue.get()

            # Check if packet is a frame
            if packet is None:
                break

            # Get frames from packet
            frames = packet.frames
            metadata = packet.metadata

            # Setup the output filename
            output_filename = "{:d}_obj_id_{:d}_cam_{:d}_frame_{:d}.mp4".format(
                metadata["ntrig"],
                metadata["obj_id"],
                metadata["camera_serial"],
                metadata["frame"],
            )

            # Setup video
            video_writer = WriteGear(
                output=output_filename,
                logging=False,
                **output_params,
            )

            # Write frames to video
            for frame in frames:
                video_writer.write(frame)

    def _check_mp(self):
        """Make sure that the multiprocessing variables are available

        Raises:
            ValueError: _description_
        """
        if hasattr(self, "event") and hasattr(self, "barrier"):
            return True
        else:
            raise ValueError("Triggered run requires event and barrier")

    def open(self):
        """
        Open the camera
        """
        self.cam.Open()

    def stop(self):
        """
        Stop the camera
        """
        self.cam.StopGrabbing()

    def close(self):
        """
        Close the camera
        """
        self.cam.Close()
