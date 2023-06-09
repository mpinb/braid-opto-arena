from pypylon import pylon
from collections import deque
import multiprocessing as mp


class ImageHandler(pylon.ImageEventHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def OnImageGrabbed(self, camera, grabResult):
        if grabResult.GrabSucceeded():
            frame = grabResult.GetArray()
            print(frame.shape)


class DequeImageHandler(pylon.ImageEventHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for key, value in kwargs.items():
            setattr(self, key, value)

        self.pre_buffer = deque(maxlen=self.fps)
        self.post_buffer = deque(maxlen=self.fps * 2)
        self.switch_buffer = False

    def OnImageGrabbed(self, camera, grabResult):
        if grabResult.GrabSucceeded():
            frame = grabResult.GetArray()


class PyCamera:
    def __init__(
        self,
        serial: str | int | None = None,
        pre_trigger_recording: bool = False,
        trigger_mode: str = "Off",
        exposure_time: int = 5000,
        gain: int = 0,
        readout_mode: str = "Normal",
        **kwargs
    ) -> None:
        # get camera data
        self.serial = serial
        self.exposure_time = exposure_time
        self.gain = gain
        self.readout_mode = readout_mode
        self.trigger_mode = trigger_mode
        self.pre_trigger_recording = pre_trigger_recording

        # parse the rest of the attributes
        for key, value in kwargs.items():
            setattr(self, key, value)

        # initialize the camera
        self.initialize()
        self.setup()

    def initialize(self):
        # connect to the cameras with serial number
        tlf = pylon.TlFactory.GetInstance()
        if self.serial is None:
            self.cam = pylon.InstantCamera(tlf.CreateFirstDevice())
        else:
            info = pylon.DeviceInfo()
            info.SetSerialNumber(str(self.serial))
            self.cam = pylon.InstantCamera(tlf.CreateDevice(info))

    def setup(self):
        # setup all the parameters
        self.cam.Open()

        self.cam.TriggerSelector = "FrameStart"
        self.cam.TriggerSource = "Line1"
        self.cam.TriggerActivation = "RisingEdge"
        self.cam.TriggerMode = self.trigger_mode
        self.cam.ExposureTime = self.exposure_time
        self.cam.Gain = self.gain
        self.cam.SensorReadoutMode = self.readout_mode

        # register the image event handler
        if self.pre_trigger_recording:
            self.cam.RegisterImageEventHandler(
                DequeImageHandler(self.trigger_event, self.fps),
                pylon.RegistrationMode_Append,
                pylon.Cleanup_Delete,
            )
        else:
            self.cam.RegisterImageEventHandler(
                ImageHandler(), pylon.RegistrationMode_Append, pylon.Cleanup_Delete
            )

    def grab(self):
        with self.cam.RetrieveResult(
            self.exposure_time, pylon.TimeoutHandling_ThrowException
        ) as grabResult:
            return grabResult.GetArray()

    def start_grabbing(self):
        self.cam.StartGrabbing(
            pylon.GrabStrategy_OneByOne, pylon.GrabLoop_ProvidedByInstantCamera
        )

    def run(self):
        try:
            self.barrier.wait()
        except AttributeError:
            pass

        while True:
            try:
                if self.kill_event:
                    break
            except AttributeError:
                pass

        self.cam.StopGrabbing()
        self.cam.Close()
