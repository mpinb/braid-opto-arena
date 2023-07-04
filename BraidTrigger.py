import csv
import json
import logging
import multiprocessing as mp
import os
import pathlib
import shutil
import time

import git
import requests
import serial
import tomllib
from vidgear.gears import WriteGear
from collections import deque
import cv2


def check_braid_folder(root_folder: str) -> str:
    """A simple function to check (and block) until a folder is created.

    Args:
        root_folder (str): the root location where we expect the .braid folder to be created.

    Returns:
        str: the path to the .braid folder.
    """
    p = pathlib.Path(root_folder)
    curr_braid_folder = list(p.glob("*.braid"))

    # loop and test as long as a folder doesn't exist
    if len(curr_braid_folder) == 0:
        logging.info(f"Waiting for .braid folder to be created in {root_folder}....")

    while len(curr_braid_folder) == 0:
        time.sleep(1)
        p = pathlib.Path(root_folder)
        curr_braid_folder = list(p.glob("*.braid"))

    logging.info(f"\nFolder {curr_braid_folder[0].as_posix()} found.")

    return curr_braid_folder[0].as_posix()


def create_flydra_proxy(flydra2_url: str) -> requests.Response:
    """A function to connect to the flydra2 server and return a requests.Response object.

    Args:
        flydra2_url (str): the url of the flydra2 server.

    Returns:
        requests.Response: a requests.Response object.
    """

    # Connect to
    flydra2_session = requests.session()
    r = flydra2_session.get(flydra2_url)
    assert r.status_code == requests.codes.ok

    # Run main flydra proxy loop
    events_url = f"{flydra2_url}/events"
    r = flydra2_session.get(
        events_url,
        stream=True,
        headers={"Accept": "text/event-stream"},
    )

    return r


def video_writer(video_writer_recv: mp.Pipe):
    """a process/thread function to loop over a pipe and write frames to a video file.

    Args:
        video_writer_recv (mp.Pipe): incoming data pipe
    """
    output_params = {
        "-input_framerate": 25,
        "-vcodec": "h264_nvenc",
        "-preset": "fast",
        "-cq": "18",
        "-disable_force_termination": True,
    }

    while True:
        folder, trigger_data, frame_buffer = video_writer_recv.recv()
        base_folder = os.path.basename(folder)
        ntrig = trigger_data["ntrig"]
        obj_id = trigger_data["obj_id"]
        cam_serial = trigger_data["cam_serial"]
        frame = trigger_data["frame"]

        output_filename = f"/home/benyishay_la/Videos/{base_folder}/{ntrig}_obj_id_{obj_id}_cam_{cam_serial}_frame_{frame}.mp4"  # noqa: E501
        logging.debug("Starting WriteGear videowriter.")
        video_writer = WriteGear(output=output_filename, logging=False, **output_params)
        logging.debug(f"Writing video to {os.path.basename(output_filename)}")
        for frame in frame_buffer:
            video_writer.write(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR))
        logging.info(
            f"Finished writing video with length {len(frame_buffer)} to {os.path.basename(output_filename)}"  # noqa: E501
        )
        video_writer.close()


def basler_camera(
    cam_serial: str | int,
    params: dict,
    camera_barrier: mp.Barrier,
    trigger_recv: mp.Pipe,
    kill_event: mp.Event,
):
    """Triggered camera function, to record frames before and after a trigger.

    Args:
        cam_serial (str | int): serial number of the camera
        params (dict): parameters dictionary
        camera_barrier (mp.Barrier): barrier to synchronize cameras
        trigger_recv (mp.Pipe): incoming trigger pipe
        kill_event (mp.Event): kill event
    """
    from pypylon import pylon

    # Connect to camera
    tlf = pylon.TlFactory.GetInstance()
    info = pylon.DeviceInfo()
    info.SetSerialNumber(str(cam_serial))
    cam = pylon.InstantCamera(tlf.CreateDevice(info))

    # Create BGR converter
    converter = pylon.ImageFormatConverter()
    converter.OutputPixelFormat = pylon.PixelType_BGR8packed
    converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

    # Set essential camera parameters
    cam.Open()
    cam.TriggerSelector = "FrameStart"
    cam.TriggerMode = "On"
    cam.TriggerSource = "Line1"
    cam.TriggerActivation = "RisingEdge"
    cam.SensorReadoutMode = "Fast"

    # Set possible camera parameters from `params`
    cam.ExposureTime = params["highspeed"].get("ExposureTime", 1900)
    cam.Gain = params["highspeed"].get("Gain", 10)

    # Setup triggered writing variables
    time_before = params["highspeed"].get("time_before", 1)
    time_after = params["highspeed"].get("time_after", 2)
    fps = params["highspeed"].get("fps", 500)
    frames_before = int(time_before * fps)
    frames_after = int(time_after * fps)
    n_total_frames = int(frames_before + frames_after)
    frame_buffer = deque(maxlen=n_total_frames)
    i_frame = 0
    trigger_set = False
    started_capture = False

    # Initialize video writer process
    video_writer_recv, video_writer_send = mp.Pipe()
    video_writer_p = mp.Process(
        target=video_writer, args=(video_writer_recv,), daemon=True
    )
    video_writer_p.start()

    # Wait until all cameras reach barrier
    logging.debug("Waiting for all cameras to reach barrier.")
    camera_barrier.wait()

    # Start grabbing
    cam.StartGrabbing(pylon.GrabStrategy_OneByOne)
    logging.info(f"Camera {cam_serial} started grabbing.")

    # Start camera
    while not kill_event.is_set():
        # Check for trigger
        trigger_set = trigger_recv.poll()

        # If trigger is set, get trigger data
        if trigger_set:
            trigger_data = trigger_recv.recv()
            trigger_data["cam_serial"] = cam_serial

        # Grab frame
        with cam.RetrieveResult(
            cam.ExposureTime + 100, pylon.TimeoutHandling_ThrowException
        ) as grabResult:
            frame_buffer.append(grabResult.Array)

        if trigger_set or started_capture:
            # Define that we want to start capturing frames
            started_capture = True
            i_frame += 1

            if i_frame == frames_after:
                # Send data to video writer
                video_writer_send.send([params["folder"], trigger_data, frame_buffer])
                logging.debug(f"Sent {len(frame_buffer)} frames to video writer.")

                # Reset counter and flag
                i_frame = 0
                started_capture = False

    cam.StopGrabbing()


def start_highspeed_cameras(params: dict, kill_event: mp.Event):
    """a wrapper function to initialize a group of highspeed cameras

    Args:
        params (dict): parameters dict
        kill_event (mp.Event): kill event

    Returns:
        highspeed_cameras: a list containing the camera processes
        highspeed_cameras_pipes: a dict containing the camera pipes
    """
    # Create a synchronization barrier for the cameras
    camera_barrier = mp.Barrier(len(params["highspeed"]["cameras"]))

    # Start camera processes
    highspeed_cameras = []
    highspeed_cameras_pipes = {}

    # Loop over cameras
    for cam_name, cam_serial in params["highspeed"]["cameras"]:
        # Create a pipe for each camera
        (
            highspeed_cameras_pipes[cam_name]["recv"],
            highspeed_cameras_pipes[cam_name]["send"],
        ) = mp.Pipe()

        # Start the process
        logging.debug(f"Creating camera {cam_name} with serial {cam_serial}.")
        p = mp.Process(
            target=basler_camera,
            args=(
                cam_serial,
                params,
                camera_barrier,
                highspeed_cameras_pipes[cam_name]["recv"],
                kill_event,
            ),
            name=f"Camera_{cam_name}",
        )
        highspeed_cameras.append(p)
        time.sleep(2)  # need to add a small delay between cameras initialization

    return highspeed_cameras, highspeed_cameras_pipes


def parse_chunk(chunk):
    """function to parse incoming chunks from the flydra2 server

    Args:
        chunk (_type_): _description_

    Returns:
        data: a dict-formatted data object
    """
    DATA_PREFIX = "data: "
    lines = chunk.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "event: braid"
    assert lines[1].startswith(DATA_PREFIX)
    buf = lines[1][len(DATA_PREFIX) :]
    data = json.loads(buf)
    return data


def create_arduino_device(port: str, baudrate: int = 9600) -> serial.Serial:
    """Simple wrapper function to create an arduino device.

    Args:
        port (str): arduino address
        baudrate (int, optional): baudrate parameter. Defaults to 9600.

    Returns:
        serial.Serial: a `board` object
    """
    board = serial.Serial(port, baudrate=baudrate, timeout=1)
    return board


def start_visual_stimuli(params: dict, trigger_event: mp.Event):
    pass


def main(params_file: str, root_folder: str):
    """Main BraidTrigger function. Starts up all processes and triggers.
    Loop over data incoming from the flydra2 proxy and tests if a trigger should be sent.

    Args:
        params_file (str): a path to the params.toml file
        root_folder (str): the root folder where the experiment folder will be created
    """
    # Load params
    with open(params_file, "rb") as f:
        params = tomllib.load(f)

    # Check if braidz is running (see if folder was created)
    folder = check_braid_folder(root_folder)
    params["folder"] = folder

    # Copy the params file to the experiment folder
    shutil.copy(params_file, folder)
    with open(os.path.join(folder, "params.toml"), "w") as f:
        f.write(
            f"commit = {git.Repo(search_parent_directories=True).head.commit.hexsha}"
        )

    # Create sessions object
    r = create_flydra_proxy(flydra2_url="http://0.0.0.0:8397/")

    # Connect to arduino
    logging.debug("Connecting to arduino.")
    opto_trigger_board = create_arduino_device(params["opto_trigger"])

    # Create kill event
    kill_event = mp.Event()

    # Connect to cameras
    if params["highspeed"]["active"]:
        # Connect to camera trigger
        camera_trigger_board = create_arduino_device(params["camera_trigger"])

        # Start camera processes
        highspeed_cameras, highspeed_cameras_pipes = start_highspeed_cameras(
            params, kill_event
        )

        # Start camera trigger
        camera_trigger_board.write(b"H")

        # Start cameras
        for cam in highspeed_cameras:
            logging.debug(f"Starting camera {cam.name}.")
            cam.start()

    # Start (static) visual stimuli
    if params["stim_params"]["static"]:
        pass

    # Start (dynamic) visual stimuli
    if params["stim_params"]["looming"] or params["stim_params"]["grating"]:
        stim_recv, stim_send = mp.Pipe()
        pass

    # Trigger parameters
    min_trajectory_time = params["trigger_params"].get(
        "min_trajectory_time", 1
    )  # seconds
    min_trigger_interval = params["trigger_params"].get(
        "min_trigger_interval", 10
    )  # seconds
    min_radius = params["trigger_params"].get("min_radius", 0.025)  # meters
    zmin = params["trigger_params"].get("zmin", 0.1)
    zmax = params["trigger_params"].get("zmax", 0.2)

    # Opto parameters
    intensity = params["opto_params"].get("intensity", 255)
    frequency = params["opto_params"].get("frequency", 0)
    duration = params["opto_params"].get("duration", 300)

    # Check parameters
    obj_ids = []
    obj_birth_times = {}
    last_trigger_time = time.time()
    ntrig = 0

    # Wait a few seconds for all processes to start
    time.sleep(5)

    # Open csv file
    with open(os.path.join(folder, "opto.csv"), "a+") as csvfile:
        # Initialize csv writer
        logging.debug("Initializing csv writer.")
        csv_writer = csv.writer(csvfile, delimiter=",")
        if os.stat(csvfile.name).st_size == 0:
            write_header = True
        else:
            write_header = False

        # Start main loop
        logging.info("Starting main loop.")
        for chunk in r.iter_content(chunk_size=None):
            if kill_event.is_set():
                break

            tcall = time.time()  # Get current time

            data = parse_chunk(chunk)  # Parse data
            version = data.get("v", 1)
            assert version == 1

            try:
                msg_dict = data["msg"]
                logging.debug(f"Message received: {msg_dict}")
            except KeyError:
                continue

            # Check for first "birth" message
            if "Birth" in msg_dict:
                curr_obj_id = msg_dict["Birth"]["obj_id"]
                logging.debug(f"New object detected: {curr_obj_id}")
                obj_ids.append(curr_obj_id)
                obj_birth_times[curr_obj_id] = tcall
                continue

            # Check for "update" message
            if "Update" in msg_dict:
                curr_obj_id = msg_dict["Update"]["obj_id"]
                if curr_obj_id not in obj_ids:
                    logging.debug(f"New object detected: {curr_obj_id}")
                    obj_ids.append(curr_obj_id)
                    obj_birth_times[curr_obj_id] = tcall
                continue

            # Check for "death" message
            if "Death" in msg_dict:
                curr_obj_id = msg_dict["Death"]
                if curr_obj_id in obj_ids:
                    logging.debug(f"Object {curr_obj_id} died")
                    obj_ids.remove(curr_obj_id)
                continue

            # if the trajectory is too short, skip
            if (tcall - obj_birth_times[curr_obj_id]) < min_trajectory_time:
                logging.debug(f"Trajectory too short for object {curr_obj_id}")
                continue

            # if the trigger interval is too short, skip
            if tcall - last_trigger_time < min_trigger_interval:
                logging.debug(f"Trigger interval too short for object {curr_obj_id}")
                continue

            # Get position and radius
            pos = msg_dict["pos"]
            radius = (pos[0] ** 2 + pos[1] ** 2) ** 0.5

            # Check if object is in the trigger zone
            if radius < min_radius and zmin <= pos["z"] <= zmax:
                logging.info(f"{ntrig}: Triggering at {tcall:.2f}")

                # Update last trigger time
                ntrig += 1
                last_trigger_time = tcall

                # Add trigger time to dict
                pos["trigger_time"] = last_trigger_time
                pos["ntrig"] = ntrig

                # Opto Trigger
                logging.debug("Triggering opto.")
                opto_trigger_time = time.time()
                opto_trigger_board.write(
                    f"<{duration},{intensity},{frequency}>".encode()
                )
                logging.debugf(
                    f"Opto trigger time: {time.time()-opto_trigger_time:.5f}"
                )

                logging.debug("Triggering cameras.")
                camera_trigger_time = time.time()
                if params["highspeed"]["active"]:
                    for _, cam_pipe in highspeed_cameras_pipes:
                        cam_pipe.send(pos)
                logging.debug(
                    f"Camera trigger time: {time.time()-camera_trigger_time:.5f}"
                )

                logging.debug("Triggering stim.")
                stim_trigger_time = time.time()
                if params["stim_params"]["looming"] or params["stim_params"]["grating"]:
                    stim_send.put(pos)
                logging.debug(f"Stim trigger time: {time.time()-stim_trigger_time:.5f}")

                # Write data to csv
                logging.debug("Writing data to csv.")
                csv_writer_time = time.time()
                if write_header:
                    csv_writer.writerow(pos.keys())
                    write_header = False
                csv_writer.writerow(pos.values())
                logging.debug(f"CSV writer time: {time.time()-csv_writer_time:.5f}")

    # Close all processes
    logging.debug("Closing all camera processes.")
    for cam in highspeed_cameras:
        cam.join()

    # Close all boards
    logging.debug("Closing all Arduino boards.")
    opto_trigger_board.close()
    camera_trigger_board.close()

    logging.info("Finished.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(processName)s-%(threadName)s: %(asctime)s - %(message)s",
    )
    main(
        params_file="./data/params.toml",
        root_folder="/media/benyishay_la/Data/Experiments/",
    )
