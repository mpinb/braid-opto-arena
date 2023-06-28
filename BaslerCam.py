import logging
import multiprocessing as mp
import threading
from collections import deque
from collections.abc import Iterable
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
        filename: str | None = None,
        kill_event: threading.Event | None = None,
    ) -> None:
        # Configure parameters
        self.params = params
        self.data = data
        self.filename = filename
        self.kill_event = kill_event

    def _check_mp(self):
        """Check input parameters do decide if we need to use multiprocessing"""
        if self.filename is None:
            if ~isinstance(self.data, Queue):
                raise ValueError("If filename is None, data must be a Queue")
            else:
                if ~isinstance(self.kill_event, threading.Event):
                    raise ValueError("If filename is None, kill_event must be an Event")
                else:
                    self.threaded_writing = True
        else:
            if isinstance(self.data, Queue):
                raise ValueError("If filename is not None, data must not be a Queue")
            else:
                self.threaded_writing = False

    def run(self) -> None:
        # Check what type of data we got
        if self.threaded_writing:
            self.looped_video_writer()
        else:
            self.write_video(self.data)

    def write_video(self, data: list | np.ndarray | DataPacket) -> None:
        """Write video to file"""

        if isinstance(data, DataPacket):
            frames = data.frames
            metadata = data.metadata
            self.filename = f"{metadata.ntrig}_obj_id_{metadata.obj_id}_cam_{metadata.camera_serial}_frame{metadata.frame}.mp4"
        else:
            frames = data

        # Initialize video writer
        video_writer = WriteGear(output=self.filename, logging=False, **self.params)

        # Write video
        for frame in frames:
            video_writer.write(frame)
        self.close()

    def looped_video_writer(self) -> None:
        try:
            while True:
                if self.kill_event.is_set() and self.data.empty():
                    break

                data = self.data.get()
                if data is None:
                    break
                self.write_video(data)
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
        self.bgr_converter()

    def _initialize(self):
        """Initialize the camera"""
        tlf = pylon.TlFactory.GetInstance()
        info = pylon.DeviceInfo()
        info.SetSerialNumber(str(self.serial))
        self.cam = pylon.InstantCamera(tlf.CreateDevice(info))

    def _set_camera_parameter(self, params: dict | None):
        """Set the camera parameters"""
        self.open()
        for key, value in params.items():
            try:
                setattr(self.cam, key, value)
                logging.debug(f"Setting {key} = {getattr(self.cam, key).Value}")
            except genicam.LogicalErrorException:
                logging.warning(f"Could not set {key} = {value}")

    def _setup_video_writer(self):
        """Start video writer thread"""
        self.frame_queue = Queue()
        self.video_writer = threading.Thread(target=self.threaded_video_writer).start()

    def grab(self):
        """Acquire a frame from the camera"""
        grabResult = self.cam.RetrieveResult(
            self.get_attr("ExposureTime") + 100, pylon.TimeoutHandling_ThrowException
        )
        image = self.converter.Convert(grabResult)
        img = image.GetArray()
        grabResult.Release()
        return img

    def open(self):
        """Open the camera"""
        self.cam.Open()

    def stop(self):
        """Stop the camera"""
        self.cam.StopGrabbing()

    def close(self):
        """Close the camera"""
        self.cam.Close()

    def bgr_converter(self):
        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = pylon.PixelType_BGR8packed
        self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

    @property
    def get_attr(self, attr: str) -> Any:
        return getattr(self.cam, attr).Value


class FreeRunBaslerCam(BaslerCam):
    def __init__(self, serial: str | int, camera_params: dict | None):
        super().__init__(serial, camera_params)

    def run(self):
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


class TriggeredBaslerCam(BaslerCam):
    def __init__(
        self,
        serial: str | int,
        camera_params: dict | None,
        mp_params: dict,
        duration: int,
    ):
        super().__init__(serial, camera_params)
        self.duration = duration
        self.fps = camera_params.get("fps", self.get_attr("ResultingFrameRate"))
        self.barrier = mp_params.get("barrier", None)
        self.kill_event = mp_params.get("kill_event", None)

        try:
            self.event = mp_params.get("event")
        except KeyError:
            raise ValueError("Must give an mp.event.")

    def run(self):
        """
        Run the camera in pre-trigger mode. The camera continously saves frames into a circular buffer.
        When the trigger is set, record until there are n+m frames in the buffer, where n+m == fps*time
        """  # noqa: E501

        # Initialize frames deque
        frames = deque(maxlen=self.fps * self.duration)
        frames_number = 0
        trigger_set = False

        # If there's a barrier, wait for it
        if hasattr(self, "barrier"):
            self.barrier.wait()

        # Start looping until keyboard interrupt
        try:
            while True:
                # First check if the kill event is set
                if self.kill_event.is_set():
                    break

                # Check if trigger is set
                trigger = self.trigger.is_set()

                # Get frame from camera
                frames.append(self.grab())

                # Check if trigger was set
                if trigger:
                    trigger_set = True

                # If the trigger was set, increment the frame number
                if trigger_set:
                    frames_number += 1

                    # And if the frame number is equal to the number of frames we want to record,
                    # put the frames into the queue and reset the frame number counter
                    if frames_number == int(self.fps * self.duration * 2 / 3):
                        self.frame_queue.put(DataPacket(frames, self.metadata))
                        frames_number = 0
                        trigger_set = True

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
        try:
            self.video_writer.join()
        except AttributeError:
            logging.debug("Video writer already closed")
