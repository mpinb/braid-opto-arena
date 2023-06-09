import logging
import multiprocessing as mp
import os
import queue
import threading
import time
from collections import deque
from datetime import datetime
import copy
import cv2
import pypylon.pylon as py
import serial
from vidgear.gears import WriteGear


def highspeed_cameras(
    trigger_event: mp.Event,
    kill_event: mp.Event,
    mp_dict: mp.Manager.dict,
    barrier: mp.Barrier,
    params: dict,
):
    highspeed_params = params["highspeed_params"]

    cameras = highspeed_params["cameras"]
    parameters = highspeed_params["parameters"]

    # initialize cameras
    logging.info("Initializing cameras...")

    # setup camera trigger
    board = serial.Serial(params["arduino_devices"]["camera_trigger"])
    board.write(b"L")

    # setup save folder
    save_folder = os.path.basename(params["folder"])[:-6]
    if not os.path.exists(f"/home/benyishay_la/Videos/{save_folder}"):
        os.mkdir(f"/home/benyishay_la/Videos/{save_folder}")

    parameters["save_folder"] = save_folder

    # setup cameras
    cameras_proc_dict = {}
    for _, camera_serial in cameras:
        cameras_proc_dict[camera_serial] = Camera(
            camera_serial,
            trigger_event,
            kill_event,
            mp_dict,
            barrier,
            parameters,
            daemon=False,
        ).start()
        time.sleep(3)

    # wait for all processes to start
    barrier.wait()

    logging.info("highspeed cameras process started.")
    board.write(b"H")
    while True:
        if kill_event.is_set():
            break

    board.write(b"L")

    for _, value in cameras_proc_dict.items():
        value.join()

    logging.info("highspeed cameras process ended.")


def video_writer(
    cam_serial: int | str, frames: list, save_folder: str, trigger_data: dict
):
    logging.info(f"{cam_serial} writing video of length {len(frames)} at {time.time()}")

    # define video parameters
    output_params = {
        "-input_framerate": 25,
        "-vcodec": "h264_nvenc",
        "-preset": "fast",
        "-cq": "18",
        "-disable_force_termination": True,
    }

    # define output filename
    video_filename = f"{trigger_data['ntrig']}_obj_id_{trigger_data['obj_id']}_cam_{cam_serial}_frame_{trigger_data['frame']}.mp4"  # noqa: E501
    output_filename = f"/home/benyishay_la/Videos/{save_folder}/{video_filename}"

    # define video writer
    video_writer = WriteGear(
        output=output_filename,
        logging=False,
        **output_params,
    )

    # write video
    for i, frame in enumerate(frames):
        bgr_frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        video_writer.write(bgr_frame)

    # close video writer
    video_writer.close()
    logging.debug(f"{cam_serial} finished video writing at {time.time()}")


class Camera(mp.Process):
    def __init__(
        self,
        serial_number: str | int,
        trigger_event: mp.Event,
        kill_event: mp.Event,
        mp_dict: mp.Manager.dict,
        barrier: mp.Barrier,
        params: dict,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)

        # define camera parameters
        self.params = params

        # define mp variables
        self.trigger_event = trigger_event
        self.kill_event = kill_event
        self.mp_dict = mp_dict
        self.barrier = barrier

        # initialize camera
        self.serial = serial
        self.tlf = py.TlFactory.GetInstance()
        self.info = py.DeviceInfo()
        self.info.SetSerialNumber(serial_number)
        self.cam = py.InstantCamera(self.tlf.CreateDevice(self.info))

        # setup camera
        self.setup_camera()

    def setup_camera(self):
        # setup all camera parameters
        self.cam.Open()
        self.cam.TriggerSelector = "FrameStart"
        self.cam.TriggerSource = "Line1"
        self.cam.TriggerActivation = "RisingEdge"
        self.cam.TriggerMode = "On"
        self.cam.ExposureTime = self.params["exposure_time"]
        self.cam.Gain = self.params["gain"]
        self.cam.SensorReadoutMode = self.params["sensor_readout_mode"]

    def run(self):
        # define capture variables
        frame_buffer_pre = deque(maxlen=500)
        frame_buffer_post = deque(maxlen=1000)
        switch_buffer = False

        got_trigger_data = False

        # wait for all barriers to be ready
        self.barrier.wait()

        # start grabbing
        self.cam.StartGrabbing(py.GrabStrategy_OneByOne)
        while True:
            # check if kill event is set
            if self.kill_event.is_set():
                break

            # check if trigger event is set
            trigger_event = self.trigger_event.is_set()

            # check if trigger event is set and if we have trigger data
            # then copy the data and set the flag to true
            if trigger_event and not got_trigger_data:
                trigger_data = copy.deepcopy(self.mp_dict)
                got_trigger_data = True

            # get frame
            with self.cam.RetrieveResult(
                5000, py.TimeoutHandling_ThrowException
            ) as grabResult:
                frame = grabResult.GetArray()

            # if it's just regular capture, append to pre_trigger_buffer
            if not trigger_event and not switch_buffer:
                frame_buffer_pre.append(frame)

            # otherwise, append to post_trigger_buffer
            if trigger_event or switch_buffer:
                frame_buffer_post.append(frame)
                switch_buffer = True

                # if the post trigger buffer is full, write the video
                if len(frame_buffer_post) == frame_buffer_post.maxlen:
                    # append both deques to a list
                    frames = list(frame_buffer_pre) + list(frame_buffer_post)

                    # start a thread to write the video
                    writer_thread = threading.Thread(  # noqa: F841
                        target=video_writer,
                        args=(
                            self.serial,
                            frames,
                            self.params["save_folder"],
                            trigger_data,
                        ),
                        daemon=True,
                    ).start()

                    # clear buffers and reset flags
                    frame_buffer_pre.clear()
                    frame_buffer_post.clear()
                    switch_buffer = False
                    got_trigger_data = False

        self.cam.StopGrabbing()
        self.cam.Close()
