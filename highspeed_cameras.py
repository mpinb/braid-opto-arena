import copy
import logging
import multiprocessing as mp
import os
import threading
import time
from collections import deque
from queue import Queue, Empty

# import cv2
import pypylon.pylon as py
from vidgear.gears import WriteGear


class CameraManager:
    def __init__(
        self,
        queue: Queue,
        kill_event: threading.Event,
        barrier: threading.Barrier,
        params: dict,
    ) -> None:
        # Threading stuff
        self.queue = queue
        self.kill_event = kill_event
        self.barrier = barrier
        self.params = params
        self.cameras = params["highspeed"]["cameras"]

    def run(self):
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
            try:
                data = self.queue.get(block=False, timeout=0.01)
            except Empty:
                continue

            self.cameras_trigger_event.set()
            data["opto_trigger_get_time"] = time.time()

    def start_cameras(self):
        # initialize all camera processes
        camera_processes = []
        for _, camera_serial in self.cameras.items():
            camera_process = mp.Process(
                target=highspeed_camera,
                args=(
                    camera_serial,
                    self.cameras_trigger_event,
                    self.kill_event,
                    self.params,
                ),
            )
            camera_processes.append(camera_process)
            time.sleep(2)

        for camera_process in camera_processes:
            camera_process.start()


def video_writer(frames_packet: Queue):
    logging.basicConfig(
        level=logging.DEBUG, format="%(processName)s: %(asctime)s - %(message)s"
    )
    # define output parameters (shared for all videos)
    output_params = {
        "-input_framerate": 25,
        "-vcodec": "h264_nvenc",
        "-preset": "fast",
        "-rc": "cbr_ld_hq",
        "-disable_force_termination": True,
    }

    # always loop, waiting for data to arrive from main process
    while True:
        logging.info("Waiting for data to arrive...")
        data = frames_packet.get()
        logging.info("Data arrived, starting to write video...")

        write_start_time = time.time()

        # setup the output filename
        logging.info("Setting up output filename...")
        output_filename = "/home/benyishay_la/Videos/{}/{:d}_obj_id_{:d}_cam_{}_frame_{:d}.mp4".format(
            data["save_folder"],
            data["ntrig"],
            data["obj_id"],
            data["camera_serial"],
            data["frame"],
        )

        # setup the video writer
        logging.info("Setting up video writer...")
        video_writer = WriteGear(
            output=output_filename,
            logging=False,
            **output_params,
        )
        logging.debug(
            f"Started writing {len(data['frame_buffer'])} frames to {output_filename}"
        )
        # write the frames
        logging.info("Writing frames...")
        for frame in data["frame_buffer"]:
            video_writer.write(frame)

        logging.info(
            "Finished writing {} frames to {} in {} seconds.".format(
                len(data["frame_buffer"]),
                os.path.basename(output_filename),
                time.time() - write_start_time,
            )
        )
        # close the video writer
        logging.info("Closing video writer...")
        video_writer.close()
        logging.info("Video writer closed.")
        frames_packet.task_done()
        logging.info("Task done.")


def highspeed_camera(
    camera_serial: str,
    save_folder: str,
    trigger_event: mp.Event,
    kill_event: mp.Event,
    mp_dict: mp.Manager().dict,
    barrier: mp.Barrier,
    got_trigger_counter: mp.Value,
    lock: mp.Lock,
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
    # cam.ExposureMode = "TriggerWidth"
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

    logging.debug(f"pre_buffer size is {pre_buffer.maxlen}")
    logging.debug(f"post_buffer size is {post_buffer.maxlen}")

    trigger = False

    # start video writer process
    frames_packet = Queue()
    video_writer_thread = threading.Thread(
        target=video_writer, args=(frames_packet,), daemon=False
    )
    video_writer_thread.start()

    converter = py.ImageFormatConverter()
    converter.OutputPixelFormat = py.PixelType_BGR8packed
    converter.OutputBitAlignment = py.OutputBitAlignment_MsbAligned

    # wait until main script and all other cameras reached the barrier
    logging.info(f"Camera {camera_serial} waiting for barrier.")
    cam.StartGrabbing(py.GrabStrategy_OneByOne)
    barrier.wait()

    # start grabbing and looping
    logging.info(f"Camera {camera_serial} passed barrier.")
    try:
        while True:
            # check if the kill event was set
            if kill_event.is_set():
                break

            # get trigger
            if trigger_event.is_set() and not trigger:
                data = copy.deepcopy(mp_dict)
                with lock:
                    got_trigger_counter.value += 1
                trigger = True
                logging.info("Got data from trigger event, set counter+=1")

            # now get the icoming frame and add to buffer
            grabtime = time.time()
            with cam.RetrieveResult(
                2000, py.TimeoutHandling_ThrowException
            ) as grabResult:
                image = converter.Convert(grabResult)
                frame = image.GetArray()
            logging.debug(f"Frame processing time is {time.time() - grabtime}")

            # if there was no trigger and we didn't switch buffer
            if not trigger:
                pre_buffer.append(frame)

            # if there was a trigger or buffer switch
            if trigger:
                post_buffer.append(frame)

                # if the post_buffer is full, send the data to the video writer and clear the buffers
                if len(post_buffer) == post_buffer.maxlen:
                    data["frame_buffer"] = list(pre_buffer) + list(post_buffer)
                    data["camera_serial"] = camera_serial
                    data["save_folder"] = save_folder
                    frames_packet.put(data)

                    pre_buffer.clear()
                    post_buffer.clear()
                    trigger = False

            # otherwise, if we still get an event and we are not in pre-trigger mode
            # just save the last frames and break
            elif (
                trigger_event.is_set()
                and params["highspeed"]["parameters"]["pre_trigger_mode"] is False
            ):
                break
    except KeyboardInterrupt:
        pass

    # clean cameras
    cam.StopGrabbing()
    cam.Close()

    # wait for the video writer to finish
    frames_packet.join()

    logging.info(f"Camera {camera_serial} finished.")
