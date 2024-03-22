from ximea import xiapi
from argparse import ArgumentParser
import time
from collections import deque
import multiprocessing as mp
import threading
import queue
import numpy as np
from matplotlib import pyplot as plt


def _set_buffers(cam):
    try:
        cam.set_acq_buffer_size(cam.get_acq_buffer_size_maximum())
    except xiapi.Xi_error as e:
        print(f"cam.set_acq_buffer_size not implemented: {e}")

    try:
        cam.set_acq_buffer_size_unit(cam.get_acq_buffer_size_unit_maximum())
    except xiapi.Xi_error as e:
        print(f"cam.set_acq_buffer_size_unit not implemented: {e}")

    try:
        cam.set_acq_transport_buffer_size(cam.get_acq_transport_buffer_size_maximum())
    except xiapi.Xi_error as e:
        print(f"cam.set_acq_transport_buffer_size not implemented: {e}")

    try:
        cam.set_acq_transport_packet_size(cam.get_acq_transport_packet_size_maximum())
    except xiapi.Xi_error as e:
        print(f"cam.set_acq_transport_packet_size not implemented: {e}")

    try:
        cam.set_buffers_queue_size(cam.get_buffers_queue_size_maximum())
    except xiapi.Xi_error as e:
        print(f"cam.set_buffers_queue_size not implemented: {e}")
    return cam


def frames_handler(frame_queue, args: dict):
    # buffers
    pre_buffer = deque(maxlen=args.time_before * args.fps)
    post_buffer = deque(maxlen=args.time_after * args.fps)

    # debug
    queue_transfer_delay = []
    queue_size = []

    # start loop
    iterations = 0
    while True:
        main_timestamp, frame = frame_queue.get()
        queue_size.append(frame_queue.qsize())
        if main_timestamp is None and frame_queue.empty():
            print("Got kill message and Queue empty")
            break

        frames_handler_timestamp = time.time()

        # print every 100 frames
        queue_transfer_delay.append(abs(main_timestamp - frames_handler_timestamp))
        if iterations % args.fps == 0:
            print(
                f"dt(frames handler queue)= {abs(main_timestamp - frames_handler_timestamp)}"
            )

        if len(pre_buffer) < pre_buffer.maxlen:
            pre_buffer.append(frame)
        elif len(post_buffer) < post_buffer.maxlen:
            post_buffer.append(frame)
        else:
            print("Buffers full")
            pre_buffer.clear()
            post_buffer.clear()

        iterations += 1

    # debugging plot
    plt.figure()
    plt.plot(queue_size)
    plt.xlabel("Frames")
    plt.ylabel("Queue size")
    plt.savefig("queue_size_over_time.png")
    plt.close()

    plt.figure()
    plt.plot(queue_transfer_delay)
    plt.xlabel("Frames")
    plt.ylabel("Queue transfer delay (s)")
    plt.savefig("queue_transfer_delay_over_time.png")
    plt.close()

    # exit
    return None


def main(args: dict):
    """
    Main function to control the camera acquisition and trigger the video_writer process

    Args:
    args (dict): Dictionary containing the camera parameters

    Returns:
    None

    """

    # create queue
    frames_queue = mp.Queue()
    frames_handler_process = mp.Process(
        target=frames_handler,
        args=(frames_queue, args),
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
    cam._set_buffers(cam)
    cam.enable_recent_frame()

    # cam.set_sensor_bit_depth("XI_BPP_8")
    cam.set_limit_bandwidth_mode("XI_ON")
    cam.set_limit_bandwidth(cam.get_limit_bandwidth_maximum())
    cam.set_exposure(args.exposure)
    cam.set_width(args.width)
    cam.set_height(args.height)
    cam.set_framerate(args.fps)

    # debug stuff
    start_time = time.time()
    iterations = 0
    runtime = 10

    # start acquisition
    print(f"Acquisition started for {runtime} seconds")
    cam.start_acquisition()

    while True:
        timestamp = time.time()

        if timestamp - start_time > runtime:
            break

        cam.get_image(img)
        frame = img.get_image_data_numpy()
        frames_queue.put((timestamp, frame))

        iterations += 1

    frames_queue.put((None, None))
    cam.stop_acquisition()
    cam.close_device()

    print("Acquisition stopped")
    print(f"Frames acquired: {iterations}")
    print(f"FPS: {iterations / (timestamp - start_time)} ({args.fps})")


if __name__ == "__main__":
    # parse arguments
    parser = ArgumentParser()
    parser.add_argument("--serial", type=str, default=None, help="Device serial number")
    parser.add_argument("--width", type=int, default=2496, help="Image width")
    parser.add_argument("--height", type=int, default=2496, help="Image height")
    parser.add_argument("--fps", type=int, default=300, help="Frames per second")
    parser.add_argument(
        "--time_before", type=int, default=1, help="Time before trigger (s)"
    )
    parser.add_argument(
        "--time_after", type=int, default=2, help="Time after trigger (s)"
    )
    parser.add_argument("--exposure", type=int, default=1000, help="Exposure time (us)")
    parser.add_argument("--verbose", type=bool, default=False, help="Verbose mode")
    args = parser.parse_args()

    main(args)
