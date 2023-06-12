import copy
import logging
import multiprocessing as mp
import threading
import time
from queue import Queue
from csv_writer import CsvWriter


def stimuli(
    trigger_event: mp.Event,
    kill_event: mp.Event,
    data_dict: mp.Manager().dict,
    barrier: mp.Barrier,
    params: dict,
):
    # import psychopy locally
    from psychopy import core, visual

    # start csv writer
    csv_queue = Queue()
    csv_kill = threading.Event()
    try:
        csv_writer = CsvWriter(
            csv_file=params["folder"] + "stim.csv",
            queue=csv_queue,
            kill_event=csv_kill,
        ).start()
    except KeyError as e:
        logging.error(f"Could not start csv writer: {e}")
        pass

    # get which stimuli are active
    show_static = params["stim_params"]["static"]["active"]
    show_looming = params["stim_params"]["looming"]["active"]
    show_grating = params["stim_params"]["grating"]["active"]

    # create window
    win = visual.Window(
        size=[640, 128],
        pos=[0, 0],
        fullscr=False,
        screen=1,
        color=[1, 1, 1],
        units="pix",
        allowGUI=False,
    )

    # create stimuli
    if show_static:
        static_params = params["stim_params"]["static"]
        static_stim = visual.ImageStim(
            win=win,
            image=static_params["image"],
            size=win.size,
            pos=[0, 0],
            units="pix",
        )

    if show_looming:
        looming_params = params["stim_params"]["looming"]
        looming_stim = visual.Circle(
            win=win,
            pos=[0, 0],
            radius=0,
            edges=100,
            units="pix",
            fillColor="black",
            lineColor="black",
            autoDraw=True,
        )

    if show_grating:
        grating_params = params["stim_params"]["grating"]
        grating_stim = visual.GratingStim(
            win=win, tex="sqr", units="pix", autoDraw=True
        )

    looming_ongoing = False
    grating_ongoing = False

    # wait for all processes to start
    barrier.wait()
    logging.info("stimuli process started.")

    # start main loop
    while True:
        # check if kill event is set
        if kill_event.is_set():
            break

        # check if trigger event is set
        if trigger_event.is_set():
            # copy data from mp_dict
            data = copy.deepcopy(data_dict)
            logging.debug(f"Got data: {data}")

            data["stimulus_start_time"] = time.time()

            # initialize stimuli
            if show_looming and not looming_ongoing:
                logging.debug("Looming stimulus going.")
                data["looming_pos_x"] = looming_stim.pos[0]
                data["looming_pos_y"] = looming_stim.pos[1]
                data["looming_radius"] = looming_stim.max_radius
                data["looming_duration"] = looming_stim.duration
                looming_ongoing = True

            if show_grating and not grating_ongoing:
                logging.debug("Grating stimulus going.")
                grating_stim.init_drift()

            data["stimulus_to_csv_writer"] = time.time()
            # send to csv writer
            csv_queue.put(data)

        # update stimuli
        if show_looming and looming_ongoing:
            looming_stim.radius += 1
            if looming_stim.radius >= looming_stim.max_radius:
                looming_stim.radius = 0
                show_looming = False
                looming_ongoing = False

        if show_grating:
            grating_stim.drift()

        if show_static:
            static_stim.draw()

        # update window
        win.update()
        core.wait(1 / 60)

    # end csv writer
    csv_kill.set()
    csv_writer.join()
    logging.info("stimuli process ended.")


if __name__ == "__main__":
    import multiprocessing

    import toml

    params = toml.load("params.toml")
    s = stimuli(
        trigger_event=mp.Event(),
        kill_event=mp.Event(),
        data_dict=mp.Manager().dict(),
        barrier=mp.Barrier(2),
        params=params,
    )


# class LoomingStimulus(Circle):
#     def __init__(
#         self, position: list | int, max_radius: int, duration: int, *args, **kwargs
#     ) -> None:
#         super().__init__(*args, **kwargs)

#         if type(position) is int:
#             self.pos = (position, 0)
#         elif type(position) is str:
#             if position == "random":
#                 self.random = True
#             else:
#                 raise ValueError("position must be 'random' or an integer")
#         else:
#             self.pos = position

#         self.max_radius = max_radius
#         self.duration = duration
#         self.do_loom = False

#     def init_loom(self):
#         if self.random:
#             self.pos = self._get_random_position()
#         self.do_loom = True

#     def loom(self):
#         # if the radius is smaller than the max radius, increase it
#         if self.radius < self.max_radius:
#             self.radius += int(self.max_radius / ((self.duration * 1e-3) / (1 / 60)))

#         # otherwise, stop the loom
#         else:
#             self.radius = 0
#             self.do_loom = False

#     def _get_random_position(self):
#         return (np.random.randint(-self.win.size[0] / 2, self.win.size[0] / 2), 0)


# class DriftingGratingStimulus(GratingStim):
#     def __init__(
#         self,
#         frequency: int,
#         orientation: int,
#         direction: int,
#         duration: int | None = None,
#         *args,
#         **kwargs,
#     ) -> None:
#         super().__init__(*args, **kwargs)

#         self.sf = frequency
#         self.ori = orientation
#         self.direction = direction
#         self.do_drift = False

#     def init_drift(self):
#         pass

#     def drift(self):
#         self.do_drift = True
#         self.phase += self.direction * self.sf * (1 / 60)
