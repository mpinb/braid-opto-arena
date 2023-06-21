import logging
import multiprocessing as mp
import queue
import time


def position_trigger(
    in_queue: mp.Queue,
    trigger_event: mp.Event,
    kill_event: mp.Event,
    mp_data_dict: mp.Manager().dict,
    barrier: mp.Barrier,
    lock: mp.Lock,
    got_trigger_counter: mp.Value,
    n_processes: int,
    params: dict,
):
    # tracking control
    curr_obj_id = None
    obj_ids = []
    obj_birth_times = {}
    ntrig = 0

    # last trigger time as current
    last_trigger = time.time()

    # wait for all processes to start
    barrier.wait()

    logging.info("PositionTrigger started.")
    while True:
        # current start loop time
        tcall = time.time()

        # check for kill event
        if kill_event.is_set():
            break

        # get chunk from queue if possible
        try:
            data = in_queue.get(block=False, timeout=0.01)
        except queue.Empty:
            # if queue is empty, continue
            continue

        # check for birth event
        if "Birth" in data:
            cur_obj_id = data["Birth"]["obj_id"]
            obj_ids.append(cur_obj_id)
            obj_birth_times[cur_obj_id] = tcall
            logging.debug(f"Birth event for {curr_obj_id}")
            continue

        # check for update event
        if "Update" in data:
            curr_obj_id = data["Update"]["obj_id"]
            logging.debug(f"Update event for {curr_obj_id}")
            if curr_obj_id not in obj_ids:
                obj_ids.append(curr_obj_id)
                obj_birth_times[curr_obj_id] = tcall
                logging.debug(f"Birth (via Update) event for {curr_obj_id}")
                continue

        # check for death event
        if "Death" in data:
            curr_obj_id = data["Death"]
            logging.debug(f"Death event for {curr_obj_id}")
            if curr_obj_id in obj_ids:
                obj_birth_times.pop(curr_obj_id)
                continue

        # check for trajectory time
        if (tcall - obj_birth_times[curr_obj_id]) < params["trigger_params"][
            "min_trajec_time"
        ]:
            logging.debug(f"Trajectory time for {curr_obj_id} too short.")
            continue

        # check for refractory time from last trigger
        if tcall - last_trigger < params["trigger_params"]["refractory_time"]:
            logging.debug("Refractory time not met.")
            continue

        # get positional data
        pos = data["Update"]
        radius = _get_radius_fast(pos, params["trigger_params"])

        # check for trigger conditions
        if (
            radius <= params["trigger_params"]["radius_min"]
            and params["trigger_params"]["zmin"]
            <= pos["z"]
            <= params["trigger_params"]["zmax"]
        ):
            logging.info(f"Triggered at {tcall:.3f}s")
            ntrig += 1
            # set trigger event
            last_trigger = tcall

            # copy all data to mp data_dict
            copy_time = time.time()
            for key, value in pos.items():
                mp_data_dict[key] = value

            # add trigger timing and number
            mp_data_dict["ntrig"] = ntrig
            mp_data_dict["position_trigger_time"] = last_trigger
            mp_data_dict["position_trigger_copy_time"] = time.time()

            logging.debug(
                f"Took {time.time() - copy_time:.3f}s to copy data to mp_dict."
            )

            # set trigger event
            trigger_time = time.time()

            # set the trigger event
            trigger_event.set()

            # wait until the trigger event is processes by all proceeses
            while got_trigger_counter.value < n_processes:
                time.sleep(0.01)

            # wait for all processes to finish
            with lock:
                got_trigger_counter.value = 0
            trigger_event.clear()

            print(f"Barrier time {time.time() - trigger_time:.3f}s")

    logging.info("PositionTrigger stopped.")


def _get_radius_fast(pos, params):
    return (
        (pos["x"] - params["center_x"]) ** 2 + (pos["y"] - params["center_y"]) ** 2
    ) ** 0.5
