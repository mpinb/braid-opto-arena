from ximea import xiapi
from argparse import ArgumentParser
import time
import multiprocessing as mp


def _set_buffers(cam):
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
    return cam


def frame_handler(frame_queue, kill_event):
    print(f"Starting frame handler {mp.current_process().name}")
    while not kill_event.is_set():
        frame = frame_queue.get()

    print(f"Stopping frame handler {mp.current_process().name}")
    return None


def main(args: dict):
    """
    Main function to control the camera acquisition and trigger the video_writer process

    Args:
    args (dict): Dictionary containing the camera parameters

    Returns:
    None

    """
    # mp queue
    frame_queue = mp.Queue()
    kill_event = mp.Event()
    # create pool of frame handlers
    print("Creating frame handlers")
    n_processes = 8
    consumer_processes = []
    for i in range(n_processes):
        p = mp.Process(
            target=frame_handler,
            args=(
                frame_queue,
                kill_event,
            ),
            name=f"frame_handler_{i}",
            daemon=True,
        )
        p.start()
        consumer_processes.append(p)

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
    runtime = 5

    # start acquisition
    print(f"Acquisition started for {runtime} seconds")
    cam.start_acquisition()

    while True:
        timestamp = time.time()

        if timestamp - start_time > runtime:
            break

        cam.get_image(img)

        frame = img.get_image_data_numpy()
        frame_queue.put(frame)
        iterations += 1

    kill_event.set()

    cam.stop_acquisition()
    cam.close_device()

    for p in consumer_processes:
        p.join()

    print("Acquisition stopped")
    print(f"Frames acquired: {iterations}")
    print(f"FPS: {iterations / (timestamp - start_time)} ({args.fps})")
    return False


if __name__ == "__main__":
    # parse arguments
    parser = ArgumentParser()
    parser.add_argument("--serial", type=str, default=None, help="Device serial number")
    parser.add_argument("--width", type=int, default=2496, help="Image width")
    parser.add_argument("--height", type=int, default=2496, help="Image height")
    parser.add_argument("--fps", type=int, default=200, help="Frames per second")
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
