import time
from argparse import ArgumentParser
from collections import deque

import numpy as np
from vidgear.gears import WriteGear
from ximea import xiapi

OUTPUT_PARAMS = {"-vcodec": "h264_nvenc", "-preset": "p1", "-tune": "ull"}


def to_ms(sec: float) -> float:
    return sec * 1000


def video_writer(frames_packets_queue):
    while True:
        # wait for a frame packet to arrive
        send_timestamp, frames_packet = frames_packets_queue.get()

        # check if the packet is a kill switch
        if frames_packet is None:
            break

        timestamp = time.time()

        # debug messages
        # print(f"Frames packet sent at {send_timestamp} received at {timestamp}")
        print(
            f"Time to send and receive: {(abs(timestamp - send_timestamp))*1000} milliseconds"
        )

        # initilalize video writer
        writer = WriteGear(
            output=f"output_{timestamp}.mp4",
            compression_mode=True,
            logging=False,
            **OUTPUT_PARAMS,
        )

        # write frames
        # print(f"Writing {len(frames_packet)} frames")
        for frame in frames_packet:
            writer.write(frame)
        # print(f"Frames writing time {abs(time.time() - timestamp)}")

        # close writer
        writer.close()


def _set_parameters(cam, args):
    # set parameters
    cam.disable_aeag()
    cam.set_imgdataformat("XI_MONO8")
    cam.enable_recent_frame()
    cam.set_limit_bandwidth_mode("XI_ON")
    cam.set_limit_bandwidth(cam.get_limit_bandwidth_maximum())
    cam.set_exposure(args.exposure)
    cam.set_width(args.width)
    cam.set_height(args.height)

    # either set the framerate or set the camera to free run
    if args.fps is not None:
        cam.set_acq_timing_mode("XI_ACQ_TIMING_MODE_FRAME_RATE_LIMIT")
        cam.set_framerate(args.fps)
    else:
        cam.set_acq_timing_mode("XI_ACQ_TIMING_MODE_FREE_RUN")
        args.fps = cam.get_framerate()
        cam.set_framerate(args.fps)

    return cam, args


def _print_dict(args):
    print("Arguments:")
    for key, value in args.items():
        print(f"{key}: {value}")


def main(args: dict):
    # create video writer process
    frames_packet_queue = Queue()
    video_writer_process = Concurrently(
        target=video_writer, args=(frames_packet_queue,)
    )
    video_writer_process.start()

    # open device
    cam = xiapi.Camera()
    if args.serial is not None:
        cam.open_device_by_SN(args.serial)
    else:
        cam.open_device()

    # create image instance
    img = xiapi.Image()

    # set parameters
    cam, args = _set_parameters(cam, args)
    _print_dict(vars(args))

    # create structured to hold data
    pre_frames = deque(maxlen=int(args.time_before * args.fps))  # 1 second
    post_frames = deque(maxlen=int(args.time_after * args.fps))  # 2 seconds

    # switch buffer trigger
    switch = False

    # debug stuff
    main_loop_start_time = time.time()
    start_time = time.time()
    iterations = 0
    runtime = 10
    frame_times = []
    to_numpy_time = []

    # start acquisition
    print(f"Acquisition started for {runtime} seconds")
    cam.start_acquisition()

    # main acquisition loop
    while True:
        timestamp = time.time()

        # break after runtime
        if timestamp - main_loop_start_time > runtime:
            break

        # get and convert image
        cam.get_image(img)

        # get numpy conversion time
        numpy_time = time.time()
        frame = img.get_image_data_numpy()
        to_numpy_time.append(time.time() - numpy_time)

        # in this case, instead of waiting for an external trigger, we will simulate it
        # by switching the buffers after 10 seconds
        if timestamp - start_time > 5 and not switch:
            trigger_time = timestamp
            if args.verbose:
                print(f"Triggered at {trigger_time}")
            switch = True

        # if we didn't get any trigger
        if not switch:
            pre_frames.append(frame)  # keep saving to 1 seconds ring buffer

        # if we did get a switch and the post_trigger buffer is not full yet
        elif switch and len(post_frames) < post_frames.maxlen:
            post_frames.append(frame)  # fill up the 2 seconds ring buffer

        # if both buffers are full
        else:
            print("Pusing frames packet to queue")
            if args.verbose:
                print(f"Saving at {time.time()}")
                print(f"{abs(time.time() - trigger_time)} after trigger")
                print(f"(should be {args.time_after + args.time_before} seconds)")

            # concatenate both buffers
            if args.verbose:
                concate_time = time.time()
            all_frames = list(pre_frames) + list(post_frames)
            if args.verbose:
                print(
                    f"Time to concatenate both buffers: {abs(time.time() - concate_time)}"
                )

            # send the concatenated buffer to the video writer process
            if args.verbose:
                time_to_queue = time.time()
            frames_packet_queue.put_nowait((timestamp, all_frames))
            if args.verbose:
                print(f"Time to send to queue: {abs(time.time() - time_to_queue)}")

            # reset both buffers
            if args.verbose:
                reset_time = time.time()

            pre_frames.clear()
            post_frames.clear()
            switch = False  # reset flag

            if args.verbose:
                print(
                    f"Time to reset buffers and flag: {abs(time.time() - reset_time)}"
                )

            # reset start_time
            start_time = time.time()

        frame_times.append(time.time() - timestamp)
        iterations += 1

    cam.stop_acquisition()
    cam.close_device()

    print(f"Acquisition stopped after {(time.time()-main_loop_start_time):.2f} seconds")
    print(f"Frames acquired: {iterations}")
    print(
        f"Average frametime {np.mean(frame_times):.5f} ({int(1/np.mean(frame_times))} FPS/{int(args.fps)} FPS)"
    )
    print(f"Average time for get_image_data_numpy {np.mean(to_numpy_time)}")

    # kill video writer process
    frames_packet_queue.put((None, None))
    return False


if __name__ == "__main__":
    # parse arguments
    parser = ArgumentParser()
    parser.add_argument(
        "--serial",
        type=str,
        default=None,
        help="Device serial number (None = first device)",
    )
    parser.add_argument(
        "--width", type=int, default=2496, help="Image width (default 2496)"
    )
    parser.add_argument(
        "--height", type=int, default=2496, help="Image height (default 2496)"
    )
    parser.add_argument(
        "--fps", type=int, default=None, help="Frames per second (None = free run)"
    )
    parser.add_argument(
        "--time_before", type=int, default=1, help="Time before trigger (s) (default 1)"
    )
    parser.add_argument(
        "--time_after", type=int, default=2, help="Time after trigger (s) (default 2)"
    )
    parser.add_argument(
        "--exposure", type=int, default=1000, help="Exposure time (us) (default 1000)"
    )
    parser.add_argument(
        "--threading",
        action="store_true",
        default=True,
        help="Use threading instead of multiprocessing",
    )
    parser.add_argument(
        "--verbose", action="store_true", default=False, help="Verbose mode"
    )
    args = parser.parse_args()

    # check if threading or multiprocessing
    if args.threading:
        from queue import Queue
        from threading import Thread as Concurrently
    else:
        from multiprocessing import Queue
        from multiprocessing import Process as Concurrently

    # run main function
    main(args)
