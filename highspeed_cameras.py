import copy
import logging
import multiprocessing as mp
import os
import threading
import time
from collections import deque
from queue import Queue

import cv2
import pypylon.pylon as py
from vidgear.gears import WriteGear


def start_highspeed_cameras(
    trigger_event: mp.Event,
    kill_event: mp.Event,
    mp_dict: mp.Manager().dict,
    barrier: mp.Barrier,
    params: dict,
):
    logging.basicConfig(
        level=logging.DEBUG, format="%(processName)s: %(asctime)s - %(message)s"
    )
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
        )
        time.sleep(3)

    for camera_process in cameras_processes:
        camera_process.start()

    while True:
        if kill_event.is_set():
            break

    [cp.join() for cp in cameras_processes]


def video_writer(frames_packet: Queue):
    logging.basicConfig(
        level=logging.DEBUG, format="%(processName)s: %(asctime)s - %(message)s"
    )
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
        output_filename = "/home/benyishay_la/Videos/{}/{:d}_obj_id_{:d}_cam_{}_frame_{:d}.mp4".format(
            data["save_folder"],
            data["ntrig"],
            data["obj_id"],
            data["camera_serial"],
            data["frame"],
        )

        # setup the video writer
        video_writer = WriteGear(
            output=output_filename,
            logging=False,
            **output_params,
        )
        logging.debug(
            f"Started writing {len(data['frame_buffer'])} frames to {output_filename}"
        )
        # write the frames
        for frame in data["frame_buffer"]:
            bgr_frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            video_writer.write(bgr_frame)

        logging.info(
            f"Finished writing {len(data['frame_buffer'])} frames to {output_filename}"
        )
        # close the video writer
        video_writer.close()


def highspeed_camera(
    camera_serial: str,
    save_folder: str,
    trigger_event: mp.Event,
    kill_event: mp.Event,
    mp_dict: mp.Manager().dict,
    barrier: mp.Barrier,
    lock: mp.Lock,
    got_trigger_counter: mp.Value,
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

    # time_ratio means how much time before the trigger we want to record
    data = {}

    # buffers
    pre_buffer = deque(maxlen=int(fps * time_before))
    post_buffer = deque(maxlen=int(fps * time_after))
    switch_buffer = False
    got_trigger_data = False

    # start video writer process
    frames_packet = Queue()
    video_writer_process = threading.Thread(
        target=video_writer, args=(frames_packet,), daemon=True
    )
    video_writer_process.start()

    # wait until main script and all other cameras reached the barrier
    logging.info(f"Camera {camera_serial} waiting for barrier.")
    barrier.wait()

    # start grabbing and looping
    cam.StartGrabbing(py.GrabStrategy_OneByOne)
    logging.info(f"Camera {camera_serial} passed barrier.")

    while True:
        # check if the kill event was set
        if kill_event.is_set():
            break

        # get trigger
        trigger = trigger_event.is_set()

        # if trigger and we didn't get data yet
        if trigger and not got_trigger_data:
            with lock:
                got_trigger_counter.value += 1
            data = copy.deepcopy(mp_dict)
            got_trigger_data = True

        # now get the icoming frame and add to buffer
        with cam.RetrieveResult(2000, py.TimeoutHandling_ThrowException) as grabResult:
            frame = grabResult.GetArray()

        # if there was no trigger and we didn't switch buffer
        if not trigger and not switch_buffer:
            pre_buffer.append(frame)

        # if there was a trigger or buffer switch
        if trigger or switch_buffer:
            post_buffer.append(frame)
            switch_buffer = True

            # if the post_buffer is full, send the data to the video writer and clear the buffers
            if len(post_buffer) == post_buffer.maxlen:
                data["frame_buffer"] = list(pre_buffer) + list(post_buffer)
                data["camera_serial"] = camera_serial
                data["save_folder"] = save_folder
                frames_packet.put(data)

                pre_buffer.clear()
                post_buffer.clear()
                got_trigger_data = False
                switch_buffer = False

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
        data["frame_buffer"] = copy.deepcopy(frame_buffer)
        data["camera_serial"] = camera_serial
        data["save_folder"] = save_folder
        frames_packet.put(data)

    cam.StopGrabbing()
    cam.Close()
    logging.info(f"Camera {camera_serial} finished.")
