import multiprocessing as mp
import os
import signal
import time

import serial
from pypylon import pylon as py
from vidgear.gears import WriteGear

CAMERA_PARAMS = {
    "Gain": 5,
    "ExposureTime": 10000,
    "TriggerMode": "On",
    "TriggerSelector": "FrameStart",
    "TriggerSource": "Line1",
    "TriggerActivation": "RisingEdge",
    "SensorReadoutMode": "Fast",
}

VIDEO_PARAMS = {
    "-input_framerate": 25,
    "-vcodec": "h264_nvenc",
    "-preset": "fast",
    "-rc": "cbr_ld_hq",
    "-disable_force_termination": True,
}

CAMERA_SERIALS = ["23047980", "23096298", "23088879", "23088882"]
KILL_SWITCH = mp.Event()
BARRIER = mp.Barrier(len(CAMERA_SERIALS) + 1)


def signal_handler(signal, frame):
    KILL_SWITCH.set()
    board.write(b"L")
    time.sleep(1)


def camera(serial: str):
    info = py.DeviceInfo()
    info.SetSerialNumber(serial)
    cam = py.InstantCamera(py.TlFactory.GetInstance().CreateFirstDevice(info))

    # Set parameters
    cam.Open()
    for k, v in CAMERA_PARAMS.items():
        setattr(cam, k, v)

    # Create BGR converter
    converter = py.ImageFormatConverter()
    converter.OutputPixelFormat = py.PixelType_BGR8packed
    converter.OutputBitAlignment = py.OutputBitAlignment_MsbAligned

    # Create video writer
    filename = os.path.join(os.getcwd(), f"{serial}.mp4")
    video_writer = WriteGear(output=filename, logging=False, **VIDEO_PARAMS)

    # Wait for all cameras to be ready
    BARRIER.wait()

    # Start grabbing
    cam.StartGrabbing(py.GrabStrategy_OneByOne)
    while not KILL_SWITCH.is_set():
        with cam.RetrieveResult(
            CAMERA_PARAMS["ExposureTime"], py.TimeoutHandling_ThrowException
        ) as grab_result:
            if grab_result.GrabSucceeded():
                image = converter.Convert(grab_result)
                image = image.GetArray()
                video_writer.write(image)

    # Stop grabbing and close video writer
    cam.StartGrabbing()
    video_writer.close()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)

    board = serial.Serial("/dev/camera_trigger", 9600)

    for cam_serial in CAMERA_SERIALS:
        mp.Process(target=camera, args=(cam_serial,), daemon=False).start()
        time.sleep(2)

    BARRIER.wait()
    board.write(b"H")
    while True:
        time.sleep(0.1)
    board.write(b"L")
