import logging
import multiprocessing as mp
import threading
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from queue import Queue
from typing import Any

import numpy as np
from pypylon import genicam, pylon
from vidgear.gears import WriteGear


@dataclass
class MetaData:
    ntrig: int
    obj_id: int
    camera_serial: int
    frame: int


@dataclass
class DataPacket:
    frames: Iterable
    metadata: MetaData


class VideoWriter:
    def __init__(
        self,
        params: dict,
        data: Queue | None | list | np.ndarray,
        filename: str | None,
    ) -> None:
        self.params = params
        self.data = data
        self.filename = filename

        if self.filename is None:
            raise ValueError("Must give a proper filename.")

        self.writer = WriteGear(output=filename, logging=False, **self.params)

    def run(self) -> None:
        # Check what type of data we got
        if isinstance(self.data, Queue.queue):
            self.looped_video_writer()
        elif isinstance(self.data, list) or isinstance(self.data, np.ndarray):
            self.write_video()
        else:
            raise ValueError("Must give a proper data type.")

    def write_video(self) -> None:
        # write video immediatly
        for frame in self.data:
            self.writer.write(frame)
        self.close()

    def looped_video_writer(self) -> None:
        try:
            while True:
                data = self.data.get()
                if data is None:
                    break
                self.write_video(data.frames)
        except KeyboardInterrupt:
            pass
        self.close()

    def close(self) -> None:
        self.writer.close()


class BaslerCam:
    def __init__(self, serial: str | int, camera_params: dict | None):
        # Get arguments
        self.serial = serial

        # Initialize camera
        self._initialize()
        self._set_camera_parameter(camera_params)

    def _initialize(self):
        """
        Initialize the camera
        """

        # Initialize camera
        tlf = pylon.TlFactory.GetInstance()
        info = pylon.DeviceInfo()
        info.SetSerialNumber(str(self.serial))
        self.cam = pylon.InstantCamera(tlf.CreateDevice(info))

    def _set_camera_parameter(self, params: dict | None):
        """
        Set the camera parameters
        """

        # Set camera parameters
        self.open()
        for key, value in params.items():
            try:
                setattr(self.cam, key, value)
                logging.debug(f"Setting {key} = {getattr(self.cam, key).Value}")
            except genicam.LogicalErrorException:
                logging.warning(f"Could not set {key} = {value}")

    def _setup_video_writer(self):
        # Start video writer thread
        self.frame_queue = Queue()
        self.video_writer = threading.Thread(target=self.threaded_video_writer).start()

    def run(self):
        """
        Main wrapper to start camera recording
        """
        self._setup_video_writer()

        # If the camera is set to free run, start the camera in free run mode
        if self.run_type == "free_run":
            self.free_run()

        # If the camera is set to triggered run, start the camera in triggered run mode
        elif self.run_type == "triggered_run":
            if self._check_mp():
                self.triggered_run()

        # If the camera is set to something else, raise an error
        else:
            self.frame_queue.put(None)
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

        # Start grabbing
        self.cam.StartGrabbing(pylon.GrabStrategy_OneByOne)

        # Start looping until keyboard interrupt
        try:
            while True:
                frames.append(self.grab())

        # If there's a keyboard interrupt, put the frames into the queue
        except KeyboardInterrupt:
            self.frame_queue.put(DataPacket(frames, self.metadata))
            pass

        # Stop the camera
        self.stop()

        # Close the camera
        self.close()

        # Put None into the queue to signal the video writer to stop
        self.frame_queue.put(None)

        # try to close the video_writer if it's still alive
        try:
            self.video_writer.join()
        except AttributeError:
            pass

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
                frames.append(self.grab())

                # Check if trigger was set
                if trigger:
                    trigger_set = 1

                # If the trigger was set, increment the frame number
                if trigger_set:
                    frames_number += 1

                    # And if the frame number is greater than the fps*time
                    # put the frames into the queue, and reset the frame number
                    if frames_number >= self.fps * self.time:
                        self.frame_queue.put(DataPacket(frames, self.metadata))
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
        self.frame_queue.put(None)
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
            packet = self.frame_queue.get()

            # Check if packet is a frame
            if packet is None:
                break

            # Get frames from packet
            frames = packet.frames
            metadata = packet.metadata

            # Setup the output filename
            output_filename = "{:d}_obj_id_{:d}_cam_{}_frame_{:d}.mp4".format(
                metadata.ntrig,
                metadata.obj_id,
                metadata.camera_serial,
                metadata.frame,
            )

            # Setup video
            video_writer = WriteGear(
                output=output_filename,
                logging=False,
                **output_params,
            )
            print("Writing to {}".format(output_filename))
            # Write frames to video
            for frame in frames:
                video_writer.write(frame)
            print("Finished writing to {}".format(output_filename))

    def _check_mp(self):
        """Make sure that the multiprocessing variables are available

        Raises:
            ValueError: _description_
        """
        if hasattr(self, "event") and hasattr(self, "barrier"):
            return True
        else:
            raise ValueError("Triggered run requires event and barrier")

    def grab(self):
        """Acquire a frame from the camera

        Returns:
            _type_: _description_
        """

        # Grab frame from camera
        with self.cam.RetrieveResult(
            self.exposure_time + 100, pylon.TimeoutHandling_ThrowException
        ) as grabResult:
            return grabResult.GetArray()

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

    @property
    def exposure_time(self):
        return int(self.cam.ExposureTime.Value)


class FreeRunBaslerCam(BaslerCam):
    def __init__(self, serial: str | int, camera_params: dict | None):
        super().__init__(serial, camera_params)

    def run(self):
        pass


class TriggeredBaslerCam(BaslerCam):
    def __init__(self, serial: str | int, camera_params: dict | None):
        super().__init__(serial, camera_params)

    def run(self):
        pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    cam = mp.Process(
        target=BaslerCam,
        args=(
            "23047980",
            {
                "ExposureTime": 1900,
                "SensorReadoutMode": "Fast",
                "TriggerMode": "Off",
                "tr": "0",
            },
        ),
    )
    cam.start()

    print("Running")
    try:
        while True:
            time.sleep(1 / 500)
    except KeyboardInterrupt:
        print("Keyboard interrupt")
        pass
    cam.join()
