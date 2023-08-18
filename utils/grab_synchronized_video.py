import multiprocessing as mp
import os
import time

import cv2
import serial
from pypylon import pylon as py
from vidgear.gears import WriteGear

CAMERA_PARAMS = {
    "Gain": 0,
    "ExposureTime": 5000,
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


def camera(serial: str, show_video: bool = True):
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
    filename = os.path.join(
        "/home/benyishay_la/Videos/20230814_charuco_calibration/",
        f"{serial}_100fps.mp4",
    )
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
                if show_video:
                    cv2.imshow(f"{serial}", image)
                    cv2.waitKey(1)

    # Stop grabbing and close video writer
    cv2.destroyAllWindows()
    cam.StartGrabbing()
    video_writer.close()


if __name__ == "__main__":
    board = serial.Serial("/dev/camera_trigger", 9600)
    ps = []
    for cam_serial in CAMERA_SERIALS:
        p = mp.Process(target=camera, args=(cam_serial,), daemon=False)
        p.start()
        ps.append(p)
        time.sleep(1)

    BARRIER.wait()
    board.write(b"100")
    kill = input("Kill? (y): ")
    KILL_SWITCH.set()
    board.write(b"0")

    for p in ps:
        p.join()
