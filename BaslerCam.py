import logging
import multiprocessing as mp
import os
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from queue import Queue, Empty
from threading import Event, Thread
from typing import Any
import time
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


class VideoWriter(Thread):
    def __init__(
        self,
        params: dict,
        incoming_data: Queue | None | list | np.ndarray = None,
        filename: str | None = None,
        kill_event: Event | None = None,
    ) -> None:
        # Configure parameters
        self.params = params
        self.incoming_data = incoming_data
        self.filename = filename
        self.kill_event = kill_event

    def _check_mp(self):
        """Check input parameters do decide if we need to use multiprocessing"""
        if self.filename is None:
            if ~isinstance(self.incoming_data, Queue):
                raise ValueError("If filename is None, data must be a Queue")
            else:
                if ~isinstance(self.kill_event, Event):
                    raise ValueError("If filename is None, kill_event must be an Event")
                else:
                    self.threaded_writing = True
        else:
            if isinstance(self.incoming_data, Queue):
                raise ValueError("If filename is not None, data must not be a Queue")
            else:
                self.threaded_writing = False

    def run(self) -> None:
        # Check what type of data we got
        if self.threaded_writing:
            self.looped_video_writer()
        else:
            self.write_video(self.incoming_data)

    def write_video(self, data: list | np.ndarray | DataPacket) -> None:
        """Write video to file"""

        if isinstance(data, DataPacket):
            # If the data is in the DataPacket format, meaning it came from a queue
            # we need to unpack it
            frames = data.frames
            metadata = data.metadata
            self.filename = (
                "/home/benyishay_la/Videos/{}/{}_obj_id_{}_cam_{}_frame{}.mp4".format(
                    metadata.folder,
                    metadata.ntrig,
                    metadata.obj_id,
                    metadata.camera_serial,
                    metadata.frame,
                )
            )
            logging.debug(f"Writing video {self.filename}")
        else:
            frames = data

        # Initialize video writer
        video_writer = WriteGear(output=self.filename, logging=False, **self.params)

        # Write video
        for frame in frames:
            video_writer.write(frame)

        logging.info(
            f"Finished writing video {os.path.basename(self.filename)} with length {len(frames)}"  # noqa: E501
        )
        video_writer.close()

    def looped_video_writer(self) -> None:
        logging.debug("Starting looped video writer")
        while True:
            # Check if the kill_event is set, but also that the queue is empty
            if self.kill_event.is_set() and self.incoming_data.empty():
                break

            # Block here, wait for data to come
            data = self.incoming_data.get()

            # Break if data is None
            if data is None:
                break

            # Write video
            self.write_video(data)

        logging.debug("Exited looped video writer")


class BaslerCam(mp.Process):
    def __init__(
        self,
        serial: str | int,
        camera_params: dict | None = None,
        *args,
        **kwargs,
    ) -> None:
        super(BaslerCam, self).__init__(*args, **kwargs)

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

        # Loop over all the dict items and set the camera parameters
        # If the parameter doesn't exist, raise a warning
        try:
            for key, value in params.items():
                try:
                    setattr(self.cam, key, value)
                    logging.debug(f"Setting {key} = {getattr(self.cam, key).Value}")
                except genicam.LogicalErrorException:
                    raise Warning(f"Could not find {key}.")
        except AttributeError:
            raise Warning("No camera parameters were passed.")

        self.close()

    def grab(self):
        """Acquire a frame from the camera"""
        tgrab = time.time()
        grabResult = self.cam.RetrieveResult(
            self.get_attr("ExposureTime") + 100, pylon.TimeoutHandling_ThrowException
        )

        # Convert to opencv bgr format
        image = self.converter.Convert(grabResult)
        img = image.GetArray()
        grabResult.Release()
        logging.debug(f"Frame grab time = {time.time() - tgrab}")
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
        """Define to OpenCV BGR converter"""
        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = pylon.PixelType_BGR8packed
        self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

    @property
    def get_attr(self, attr: str) -> Any:
        return getattr(self.cam, attr).Value


class TriggeredBaslerCam(BaslerCam):
    def __init__(
        self,
        serial: str | int,
        camera_params: dict | None,
        barrier: mp.Barrier,
        kill_event: mp.Event,
        incoming_data_queue: mp.Queue,
        *args,
        **kwargs,
    ):
        super().__init__(serial, camera_params, *args, **kwargs)

        # Multiprocessing stuff
        self.barrier = barrier
        self.kill_event = kill_event
        self.incoming_data_queue = incoming_data_queue

        # Capture stuff
        self.fps = camera_params.get("fps", self.get_attr("ResultingFrameRate"))
        self.duration = camera_params.get("duration", 3)
        self.ratio = camera_params.get("ratio", 1 / 3)
        self.frames_before = int(self.fps * self.duration * self.ratio)
        self.frames_after = int(self.fps * self.duration * (1 - self.ratio))

    def run(self):
        """
        Run the camera in pre-trigger mode. The camera continously saves frames into a circular buffer.
        When the trigger is set, record until there are n+m frames in the buffer, where n+m == fps*time
        """  # noqa: E501

        # Initialize frames deque
        frames_buffer = deque(maxlen=self.frames_before + self.frames_after)
        frames_number = 0
        trigger_set = False
        started_capture = False

        # Start video writer
        self._video_writer()

        # Wait for the barrier
        logging.debug("Waiting for barrier.")
        self.barrier.wait()

        # Start looping until keyboard interrupt
        logging.info("Starting main loop.")
        while not self.kill_event.is_set():
            # Using try and except with a queue instead of an event
            try:
                metadata = self.incoming_data_queue.get_nowait()
                trigger_set = True
            except Empty:
                trigger_set = False

            # Append frame to frames buffer
            frames_buffer.append(self.grab())

            # If the trigger was set, increment the frame number
            # We need to add the `started_capture` flag as `trigger_set`
            # will reset in the next loop when it tries to get another
            # data packet from the queue
            if trigger_set or started_capture:
                started_capture = True
                frames_number += 1

                # Dump frames to video writer if we recorded the defined number of fraes
                if frames_number == self.frames_after:
                    self.video_writer_queue.put(DataPacket(frames_buffer, metadata))
                    frames_number = 0
                    started_capture = False

        logging.debug("Exited main loop.")

        # Stop the camera
        self.stop()

        # Close the camera
        self.close()

        # Put None into the queue to signal the video writer to stop
        self.video_writer_queue.put(None)

        logging.info("Process finished.")

    def _video_writer(self):
        output_params = {
            "-input_framerate": 25,
            "-vcodec": "h264_nvenc",
            "-preset": "fast",
            "-rc": "cbr_ld_hq",
            "-disable_force_termination": True,
        }

        # Initialize the kill event and queue
        self.video_writer_kill_event = Event()
        self.video_writer_queue = Queue()

        # Start the video writer
        self.video_writer = VideoWriter(
            params=output_params,
            incoming_data=self.video_writer_queue,
            kill_event=self.video_writer_kill_event,
        ).start()


class FreeRunBaslerCam(BaslerCam):
    def __init__(self, serial: str | int, camera_params: dict | None, *args, **kwargs):
        super(FreeRunBaslerCam, self).__init__(serial, camera_params, *args, **kwargs)

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
