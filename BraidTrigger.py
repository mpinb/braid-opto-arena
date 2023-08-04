import logging
import multiprocessing as mp
import os
import shutil
import signal
import time
import tomllib

import git
import requests

from basler_camera import start_highspeed_cameras
from helper_functions import (
    check_braid_folder,
    create_arduino_device,
    create_csv_writer,
    parse_chunk,
)
from utils.rspowersupply import PowerSupply
from visual_stimuli import start_visual_stimuli


def main(params_file: str, root_folder: str):
    """Main BraidTrigger function. Starts up all processes and triggers.
    Loop over data incoming from the flydra2 proxy and tests if a trigger should be sent.

    Args:
        params_file (str): a path to the params.toml file
        root_folder (str): the root folder where the experiment folder will be created
    """
    # Load params
    with open(params_file, "rb") as f:
        params = tomllib.load(f)

    # Check if braidz is running (see if folder was created)
    folder = check_braid_folder(root_folder)
    params["folder"] = folder

    # Copy the params file to the experiment folder
    shutil.copy(params_file, folder)
    with open(os.path.join(folder, "params.toml"), "w") as f:
        f.write(
            f"commit = {git.Repo(search_parent_directories=True).head.commit.hexsha}"
        )

    ps = PowerSupply()
    ps.set_voltage(30)

    # Connect to arduino
    if params["opto_params"]["active"]:
        logging.debug("Connecting to arduino.")
        opto_trigger_board = create_arduino_device(
            params["arduino_devices"]["opto_trigger"]
        )

    # Create mp variables
    kill_event = mp.Event()
    signal.signal(signal.SIGINT, lambda signal, frame: kill_event.set())

    # Connect to flydra2 proxy
    flydra2_url = "http://0.0.0.0:8397/"
    session = requests.Session()
    r = session.get(flydra2_url)
    assert r.status_code == requests.codes.ok
    events_url = r.url + "events"

    # Connect to cameras
    if params["highspeed"]["active"]:
        # Connect to camera trigger
        camera_trigger_board = create_arduino_device(
            params["arduino_devices"]["camera_trigger"]
        )
        camera_trigger_board.write(b"L")  # reset camera trigger

        # Start camera processes
        (
            highspeed_cameras,
            highspeed_cameras_pipes,
            camera_barrier,
        ) = start_highspeed_cameras(params, kill_event)

        # Start cameras
        for cam in highspeed_cameras:
            logging.debug(f"Starting camera {cam.name}.")
            cam.start()
            time.sleep(2)  # Delay between starting each camera process

        camera_barrier.wait()  # Wait for all cameras to be ready
        camera_trigger_board.write(b"500")  # Start camera trigger

    # Start (dynamic) visual stimuli
    if (
        params["stim_params"]["static"]["active"]
        or params["stim_params"]["looming"]["active"]
        or params["stim_params"]["grating"]["active"]
    ):
        stim_recv, stim_send = mp.Pipe()
        stimulus_process = mp.Process(
            target=start_visual_stimuli,
            args=(params, stim_recv, kill_event),
            name="VisualStimuli",
        )
        stimulus_process.start()

    # Trigger parameters
    min_trajectory_time = params["trigger_params"].get(
        "min_trajectory_time", 1
    )  # seconds
    min_trigger_interval = params["trigger_params"].get(
        "min_trigger_interval", 10
    )  # seconds
    min_radius = params["trigger_params"].get("min_radius", 0.025)  # meters
    zmin = params["trigger_params"].get("zmin", 0.1)
    zmax = params["trigger_params"].get("zmax", 0.2)

    # Opto parameters
    intensity = params["opto_params"].get("intensity", 255)
    frequency = params["opto_params"].get("frequency", 0)
    duration = params["opto_params"].get("duration", 300)

    csv_file, csv_writer, write_header = create_csv_writer(params["folder"], "opto.csv")

    # Check parameters
    obj_ids = []
    obj_birth_times = {}
    last_trigger_time = time.time()
    ntrig = 0

    # Wait a few seconds for all processes to start
    time.sleep(5)

    # Start main loop
    logging.info("Starting main loop.")
    with session.get(
        events_url, stream=True, headers={"Accept": "text/event-stream"}
    ) as r:
        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            if kill_event.is_set():
                break

            tcall = time.time()  # Get current time
            data = parse_chunk(chunk)

            try:
                msg_dict = data["msg"]
            except KeyError:
                continue

            # logging.info(f"Received message: {msg_dict}")

            # Check for first "birth" message
            if "Birth" in msg_dict:
                curr_obj_id = msg_dict["Birth"]["obj_id"]
                logging.debug(f"New object detected: {curr_obj_id}")
                obj_ids.append(curr_obj_id)
                obj_birth_times[curr_obj_id] = tcall
                continue

            # Check for "update" message
            if "Update" in msg_dict:
                curr_obj_id = msg_dict["Update"]["obj_id"]
                if curr_obj_id not in obj_ids:
                    logging.debug(f"New object detected: {curr_obj_id}")
                    obj_ids.append(curr_obj_id)
                    obj_birth_times[curr_obj_id] = tcall
                    continue

            # Check for "death" message
            if "Death" in msg_dict:
                curr_obj_id = msg_dict["Death"]
                if curr_obj_id in obj_ids:
                    logging.debug(f"Object {curr_obj_id} died")
                    obj_ids.remove(curr_obj_id)
                continue

            # if the trajectory is too short, skip
            if (tcall - obj_birth_times[curr_obj_id]) < min_trajectory_time:
                # logging.warning(f"Trajectory too short for object {curr_obj_id}")
                continue

            # if the trigger interval is too short, skip
            if tcall - last_trigger_time < min_trigger_interval:
                # logging.warning(f"Trigger interval too short for object {curr_obj_id}")
                continue

            # Get position and radius
            pos = msg_dict["Update"]
            radius = (pos["x"] ** 2 + pos["y"] ** 2) ** 0.5

            # Check if object is in the trigger zone
            if radius < min_radius and zmin <= pos["z"] <= zmax:
                logging.info(f"Trigger {ntrig} at {radius}, {pos['z']}")

                # Update last trigger time
                ntrig += 1
                last_trigger_time = tcall

                # Add trigger time to dict
                pos["trigger_time"] = last_trigger_time
                pos["ntrig"] = ntrig

                # Opto Trigger
                if params["opto_params"]["active"]:
                    logging.debug("Triggering opto.")
                    opto_trigger_time = time.time()
                    opto_trigger_board.write(
                        f"<{duration},{intensity},{frequency}>".encode()
                    )
                    pos["opto_duration"] = duration
                    pos["opto_intensity"] = intensity
                    pos["opto_frequency"] = frequency
                    logging.debug(
                        f"Opto trigger time: {time.time()-opto_trigger_time:.5f}"
                    )

                logging.debug("Triggering cameras.")
                camera_trigger_time = time.time()
                if params["highspeed"]["active"]:
                    for _, cam_pipe in highspeed_cameras_pipes.items():
                        cam_pipe["send"].send(pos)
                logging.debug(
                    f"Camera trigger time: {time.time()-camera_trigger_time:.5f}"
                )

                # Stim Trigger
                logging.debug("Triggering stim.")
                stim_trigger_time = time.time()
                if (
                    params["stim_params"]["looming"]["active"]
                    or params["stim_params"]["grating"]["active"]
                ):
                    stim_send.send(pos)
                logging.debug(f"Stim trigger time: {time.time()-stim_trigger_time:.5f}")

                # Write data to csv
                if params["opto_params"]["active"]:
                    logging.debug("Writing data to csv.")
                    csv_writer_time = time.time()
                    if write_header:
                        csv_writer.writerow(pos.keys())
                        write_header = False
                    csv_writer.writerow(pos.values())
                    csv_file.flush()
                    logging.debug(f"CSV writer time: {time.time()-csv_writer_time:.5f}")

    # Close all processes
    logging.debug("Closing all camera processes.")
    for cam in highspeed_cameras:
        cam.join()

    # Close all boards
    logging.debug("Closing all Arduino boards.")
    if params["opto_params"]["active"]:
        opto_trigger_board.close()
    if params["highspeed"]["active"]:
        camera_trigger_board.write(b"0")
        camera_trigger_board.close()

    # Close CSV file
    logging.debug("Closing CSV file.")
    csv_file.close()

    logging.debug("Closing power supply.")
    ps.set_voltage(0)

    logging.info("Finished.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(processName)s: %(asctime)s - %(message)s",
    )
    main(
        params_file="./data/params.toml",
        root_folder="/media/benyishay_la/Data/Experiments/",
    )
