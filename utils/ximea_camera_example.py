from ximea import xiapi
from collections import deque
import multiprocessing as mp
from argparse import ArgumentParser
from vidgear.gears import WriteGear
import time
from queue import Empty
import numpy as np


def video_writer(packets_queue: mp.Queue):
    """
    Function to write frames to a video file using VidGear WriteGear

    Args:
    queue (mp.Queue): Queue to get frames from the main process

    Returns:
    None

    """

    current_process = mp.current_process().name

    output_params = {
        "-vcodec": "h264_nvenc",
        "-preset": "p1",
        "-tune": "ull",
        "-disable_force_termination": True,
    }

    # infinite loop, writing for frames packet
    print(f"{current_process} - Starting video writer loop")
    while True:
        try:
            frames = packets_queue.get_nowait()
        except Empty:
            continue

        if frames is None:
            print(f"{current_process} - Got None; Stopping video writer")
            break

        print(f"{current_process} - Writing frames to video")
        writer = WriteGear(
            output="output_test.mp4",
            compression_mode=True,
            logging=True,
            **output_params,
        )
        for frame in frames:
            writer.write(frame)

        writer.close()
        print(f"{current_process} - Frames written to video")


def frames_handler(frames_queue: mp.Queue, event: mp.Event, args: dict):
    current_process = mp.current_process().name

    # create packets queue and video writer process
    packets_queue = mp.Queue()
    writer_process = mp.Process(target=video_writer, args=(packets_queue,))
    writer_process.start()

    # create frame buffers
    pre_buffer = deque(maxlen=args.fps)
    post_buffer = deque(maxlen=args.fps * 2)

    # start acquisition
    while True:
        timestamp = time.time()
        try:
            data_raw = frames_queue.get_nowait()
        except Empty:
            continue

        switch = event.is_set()

        if data_raw is None and not switch:
            break

        frame = np.frombuffer(data_raw, dtype=np.uint8).reshape(args.height, args.width)

        if switch:
            post_buffer.append(frame)
        else:
            pre_buffer.append(frame)

        if len(post_buffer) == post_buffer.maxlen:
            frames = concatenate_buffers(
                current_process, timestamp, pre_buffer, post_buffer, verbose=True
            )

            send_frames_to_queue(
                current_process, timestamp, frames, packets_queue, verbose=True
            )

            pre_buffer, post_buffer = clear_buffers(
                current_process, timestamp, pre_buffer, post_buffer, verbose=True
            )

            event.clear()

    packets_queue.put(None)

    print(f"{current_process}:{timestamp} - Stopping video writer")
    writer_process.join()
    print(f"{current_process}:{timestamp} - video writer stopped")


def main(args: dict):
    """
    Main function to control the camera acquisition and trigger the video_writer process

    Args:
    args (dict): Dictionary containing the camera parameters
    queue (mp.Queue): Queue to send frames to the video_writer process

    Returns:
    None

    """
    current_process = mp.current_process().name

    # create frames queue and frames handler process
    frames_queue = mp.Queue()
    event = mp.Event()
    frames_handler_process = mp.Process(
        target=frames_handler,
        args=(frames_queue, event, args),
        name="frames_handler",
    )
    frames_handler_process.start()

    # open device
    cam = xiapi.Camera()
    if args.serial is not None:
        cam.open_device_by_SN(args.serial)
    else:
        cam.open_device()

    # create image instance
    img = xiapi.Image()

    # set parameters
    cam.disable_aeag()
    cam.set_acq_timing_mode("XI_ACQ_TIMING_MODE_FRAME_RATE_LIMIT")
    cam.set_imgdataformat("XI_MONO8")

    try:
        cam.set_acq_buffer_size(cam.get_acq_buffer_size_maximum())
    except xiapi.Xi_error as e:
        print(f"{e}")

    try:
        cam.set_acq_buffer_size_unit(cam.get_acq_buffer_size_unit_maximum())
    except xiapi.Xi_error as e:
        print(f"{e}")

    try:
        cam.set_acq_transport_buffer_size(cam.get_acq_transport_buffer_size_maximum())
    except xiapi.Xi_error as e:
        print(f"{e}")

    try:
        cam.set_acq_transport_packet_size(cam.get_acq_transport_packet_size_maximum())
    except xiapi.Xi_error as e:
        print(f"{e}")

    try:
        cam.set_buffers_queue_size(cam.get_buffers_queue_size_maximum())
    except xiapi.Xi_error as e:
        print(f"{e}")

    cam.enable_recent_frame()

    # cam.set_sensor_bit_depth("XI_BPP_8")
    cam.set_limit_bandwidth_mode("XI_ON")
    cam.set_limit_bandwidth(cam.get_limit_bandwidth_maximum())
    cam.set_exposure(args.exposure)
    cam.set_width(args.width)
    cam.set_height(args.height)
    cam.set_framerate(args.fps)

    # create test flags
    start_time = time.time()
    test_flag = True

    # arrays for timings
    get_image_list = []
    to_raw_list = []
    queue_put_list = []
    total_frame_list = []

    # start acquisition
    print(f"{current_process}:{start_time} - Starting acquisition")
    cam.start_acquisition()
    try:
        while True:
            timestamp = time.time()

            # get image from camera and convert to numpy array
            get_image_time = time.time()
            cam.get_image(img)
            get_image_list.append(time.time() - get_image_time)

            # get numpy array from camera image
            to_raw_time = time.time()
            frame = img.get_image_data_raw()
            to_raw_list.append(time.time() - to_raw_time)

            # send frame to frames queue
            queue_put_time = time.time()
            frames_queue.put(frame)
            queue_put_list.append(time.time() - queue_put_time)

            total_frame_list.append(time.time() - timestamp)

            # check if test time has passed
            if time.time() - start_time > 10 and test_flag:
                event.set()
                test_flag = False

            if time.time() - start_time > 30:
                frames_queue.put(None)
                print(f"{current_process}:{timestamp} - Stopping acquisition")
                break

    except KeyboardInterrupt:
        pass

    # stop acquisition and close device
    cam.stop_acquisition()
    cam.close_device()

    # print average times
    import numpy as np

    print(f"get_image: {np.mean(get_image_list)}")
    print(f"to_raw: {np.mean(to_raw_list)}")
    print(f"queue_put: {np.mean(queue_put_list)}")
    print(
        f"total_frame: {np.mean(total_frame_list)}, fps = {1/np.mean(total_frame_list)}"
    )

    # join frames handler process
    print(f"{current_process}:{timestamp} - Stopping frames handler")
    frames_handler_process.join()
    print(f"{current_process}:{timestamp} - Frames handler stopped")


def concatenate_buffers(
    current_process, timestamp, pre_buffer, post_buffer, verbose=False
):
    if verbose:
        concat_time = time.time()
        print(f"{current_process}:{timestamp} - post_buffer full")
    frames = list(pre_buffer) + list(post_buffer)
    if verbose:
        print(
            f"{current_process}:{timestamp} - Concatenation time: {time.time() - concat_time}"
        )
    return frames


def send_frames_to_queue(
    current_process, timestamp, frames, packets_queue, verbose=False
):
    if verbose:
        queue_time = time.time()
        print(f"{current_process}:{timestamp} - Sending frames to video writer")
    packets_queue.put(frames)

    if verbose:
        print(f"{current_process}:{timestamp} - Queue time: {time.time() - queue_time}")


def clear_buffers(current_process, timestamp, pre_buffer, post_buffer, verbose=False):
    if verbose:
        clear_time = time.time()
        print(f"{current_process}:{timestamp} - Clearing buffers")

    pre_buffer.clear()
    post_buffer.clear()

    if verbose:
        print(f"{current_process}:{timestamp} - Clear time: {time.time() - clear_time}")

    return pre_buffer, post_buffer


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--serial", type=str, default=None, help="Device serial number")
    parser.add_argument("--width", type=int, default=2496, help="Image width")
    parser.add_argument("--height", type=int, default=2496, help="Image height")
    parser.add_argument("--fps", type=int, default=400, help="Frames per second")
    parser.add_argument("--exposure", type=int, default=1000, help="Exposure time (us)")
    args = parser.parse_args()

    main(args)
