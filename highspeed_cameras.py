import logging
import multiprocessing as mp
import os
import threading
import time
from collections import deque
import copy

import cv2
import pypylon.pylon as py
from vidgear.gears import WriteGear
from queue import Queue


def start_highspeed_cameras(
    trigger_event: mp.Event,
    kill_event: mp.Event,
    mp_dict: mp.Manager.dict,
    barrier: mp.Barrier,
    params: dict,
):
    # initialize cameras
    logging.info("Initializing cameras...")

    # setup save folder
    save_folder = os.path.basename(params["folder"])[:-6]
    if not os.path.exists(f"/home/benyishay_la/Videos/{save_folder}"):
        os.mkdir(f"/home/benyishay_la/Videos/{save_folder}")

    # setup cameras
    cameras_processes = []
    for _, camera_serial in params["highspeed"]["cameras"].items():
        cameras_processes.append(
            mp.Process(
                target=highspeed_camera,
                args=(
                    camera_serial,
                    save_folder,
                    trigger_event,
                    kill_event,
                    mp_dict,
                    barrier,
                    params,
                ),
                name=f"camera_{camera_serial}",
            )
        ).start()
        time.sleep(3)

    return cameras_processes


def video_writer(frames_packet: Queue):
    # define output parameters (shared for all videos)
    output_params = {
        "-input_framerate": 25,
        "-vcodec": "h264_nvenc",
        "-preset": "fast",
        "-cq": "18",
        "-disable_force_termination": True,
    }

    # always loop, waiting for data to arrive from main process
    while True:
        data = frames_packet.get()

        # setup the output filename
        output_filename = (
            "home/benyishay_la/Videos/{}/{:d}_obj_id_{:d}_cam_{}_frame_{:d}.mp4".format(
                data["save_folder"],
                data["ntrig"],
                data["obj_id"],
                data["camera_serial"],
                data["frame"],
            )
        )

        # setup the video writer
        video_writer = WriteGear(
            output=output_filename,
            logging=False,
            **output_params,
        )

        # write the frames
        for frame in data["frame_buffer"]:
            bgr_frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            video_writer.write(bgr_frame)

        # close the video writer
        video_writer.close()


def highspeed_camera(
    camera_serial: str,
    save_folder: str,
    trigger_event: mp.Event,
    kill_event: mp.Event,
    mp_dict: mp.Manager.dict,
    barrier: mp.Manager.Barrier,
    params,
):
    logging.info(f"Initializing camera {camera_serial}")

    # initialize camera
    tlf = py.TlFactory.GetInstance()
    info = py.DeviceInfo()
    info.SetSerialNumber(str(camera_serial))
    cam = py.InstantCamera(tlf.CreateDevice(info))

    # set parameters
    cam.Open()
    cam.TriggerSelector = "FrameStart"
    cam.TriggerSource = "Line1"
    cam.TriggerActivation = "RisingEdge"
    cam.TriggerMode = "On"
    cam.ExposureTime = params["highspeed"]["parameters"]["exposure_time"]
    cam.Gain = params["highspeed"]["parameters"]["gain"]
    cam.SensorReadoutMode = params["highspeed"]["parameters"]["sensor_readout_mode"]

    # fps
    if params["highspeed"]["parameters"]["fps"] is not None:
        fps = params["highspeed"]["parameters"]["fps"]
    else:
        fps = cam.ResultingFrameRate.GetValue()

    # buffer setup
    time_before = params["highspeed"]["parameters"]["time_before"]
    time_after = params["highspeed"]["parameters"]["time_after"]
    total_time = time_before + time_after
    if total_time is None:
        frame_buffer = []
    else:
        frame_buffer = deque(maxlen=int(fps * total_time))

    # time_ratio means how much time before the trigger we want to record
    frames_before = int(fps * time_before)  # noqa: F841
    frames_after = int(fps * time_after)
    data = {}

    # start video writer process
    frames_packet = Queue()
    video_writer_process = threading.Thread(
        target=video_writer, args=(frames_packet,), daemon=True
    )
    video_writer_process.start()

    # start grabbing and looping
    cam.StartGrabbing(py.GrabStrategy_OneByOne)

    # wait until main script and all other cameras reached the barrier
    barrier.wait()
    logging.debug(f"Camera {camera_serial} passed barrier.")

    while True:
        # check if the kill event was set
        if kill_event.is_set():
            break

        # now get the icoming frame and add to buffer
        with cam.RetrieveResult(2000, py.TimeoutHandling_ThrowException) as grabResult:
            frame_buffer.append(grabResult.GetArray())

        # check if the trigger event was set
        if (
            trigger_event.is_set()
            and params["highspeed"]["parameters"]["pre_trigger_mode"]
        ):
            # get data from mp_dict
            data = copy.deepcopy(mp_dict)

            # now we loop for the next n frames (according to fps)
            for _ in range(frames_after):
                with cam.RetrieveResult(
                    2000, py.TimeoutHandling_ThrowException
                ) as grabResult:
                    frame_buffer.append(grabResult.GetArray())

            # and once we're done, we put the data in the queue
            data["frame_buffer"] = frame_buffer
            data["camera_serial"] = camera_serial
            data["save_folder"] = save_folder

            # and send it to the video writer thread
            frames_packet.put(data)

        # otherwise, if we still get an event and we are not in pre-trigger mode
        # just save the last frames and break
        elif (
            trigger_event.is_set()
            and params["highspeed"]["parameters"]["pre_trigger_mode"] is False
        ):
            break

    # if we are using continous recording
    if params["highspeed"]["parameters"]["pre_trigger_mode"] is False:
        data["ntrig"] = 0
        data["obj_id"] = 0
        data["frame"] = 0
        data["frame_buffer"] = frame_buffer
        data["camera_serial"] = camera_serial
        data["save_folder"] = save_folder
        frames_packet.put(data)

    cam.StopGrabbing()
    cam.Close()
