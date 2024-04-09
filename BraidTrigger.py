import argparse
import logging
import multiprocessing as mp
import os
import random
import shutil
import time
import zmq
import zmq.utils.monitor as zmon
import git
import requests
import tomllib
import subprocess

from basler_camera import start_highspeed_cameras
from helper_functions import (
    check_braid_folder,
    create_arduino_device,
    create_csv_writer,
    parse_chunk,
    zmq_pubsub,
)
import json
from rspowersupply import PowerSupply
from visual_stimuli import start_visual_stimuli

PSU_VOLTAGE = 30


def main(params_file: str, root_folder: str, args: argparse.Namespace):
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
    if not args.debug:
        folder = check_braid_folder(root_folder)
    else:
        folder = "./.test/"
    params["folder"] = folder

    # Copy the params file to the experiment folder
    shutil.copy(params_file, folder)
    with open(os.path.join(folder, "params.toml"), "w") as f:
        f.write(
            f"commit = {git.Repo(search_parent_directories=True).head.commit.hexsha}"
        )
    # create PUB socket
    logging.info("Creating PUB socket.")
    context = zmq.Context()
    publisher = context.socket(zmq.PUB)
    publisher.bind("tcp://127.0.0.1:5555")

    # Set power supply voltage (for backlighting)
    try:
        ps = PowerSupply(port="/dev/powersupply")
        ps.set_voltage(PSU_VOLTAGE)
    except RuntimeError:
        logging.debug("Backlight power supply not connected.")

    # Create mp variables
    kill_event = mp.Event()
    # signal.signal(signal.SIGINT, signal_handler)

    # Connect to arduino
    if args.opto:
        logging.debug("Connecting to arduino.")
        opto_trigger_board = create_arduino_device(
            params["arduino_devices"]["opto_trigger"]
        )

    # Connect to flydra2 proxy
    flydra2_url = "http://10.40.80.6:8397/"
    session = requests.Session()
    r = session.get(flydra2_url)
    assert r.status_code == requests.codes.ok
    events_url = r.url + "events"

    # Connect to cameras
    if args.highspeed:
        base_folder = os.path.splitext(os.path.basename(params["folder"]))[0]
        output_folder = f"/home/buchsbaum/mnt/DATA/Videos/{base_folder}/"
        params["video_save_folder"] = output_folder
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        if params["highspeed"]["type"] == "ximea":
            monitor_socket = publisher.get_monitor_socket(
                zmq.EVENT_ACCEPTED | zmq.EVENT_DISCONNECTED
            )

            # open rust ximea camera process
            ximea_camera_process = subprocess.Popen(
                "ximea_camera/target/release/ximea_camera"
            )

            # wait for the camera process to connect
            evt_mon = zmon.recv_monitor_message(monitor_socket)

            # send the folder to the camera process
            if evt_mon["event"] == zmq.EVENT_ACCEPTED:
                logging.info("Camera process connected.")
                publisher.send(output_folder.encode("utf-8"))

            else:
                logging.error("Camera process not connected.")
                raise ValueError("Camera process not connected.")

        elif params["highspeed"]["type"] == "basler":
            # Connect to camera trigger
            camera_trigger_board = create_arduino_device(
                params["arduino_devices"]["camera_trigger"]
            )
            camera_trigger_board.write(b"0")  # reset camera trigger

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
        else:
            logging.error("Highspeed camera type not recognized.")
            raise ValueError("Highspeed camera type not recognized.")

    # Start (dynamic) visual stimuli
    if args.static or args.looming or args.grating:
        stim_recv, stim_send = mp.Pipe()
        stimulus_process = mp.Process(
            target=start_visual_stimuli,
            args=(
                params,
                stim_recv,
                kill_event,
                args,
            ),
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
    sham_perc = params["opto_params"].get("sham_perc", 0)

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
    try:
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
                elif "Update" in msg_dict:
                    curr_obj_id = msg_dict["Update"]["obj_id"]
                    if curr_obj_id not in obj_ids:
                        logging.debug(f"New object detected: {curr_obj_id}")
                        obj_ids.append(curr_obj_id)
                        obj_birth_times[curr_obj_id] = tcall
                        continue
                # Check for "death" message
                elif "Death" in msg_dict:
                    curr_obj_id = msg_dict["Death"]
                    if curr_obj_id in obj_ids:
                        logging.debug(f"Object {curr_obj_id} died")
                        obj_ids.remove(curr_obj_id)
                    continue

                else:
                    logging.debug("No relevant message.")
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
                # in_position = radius < min_radius and zmin <= pos["z"] <= zmax

                # Check if object is in the trigger zone
                in_position = (
                    zmin <= pos["z"] <= zmax
                    and -0.05 <= pos["x"] <= 0.036
                    and -0.027 <= pos["y"] <= 0.06
                )

                if in_position:
                    logging.info(f"Trigger {ntrig} at {radius}, {pos['z']}")

                    # Update last trigger time
                    ntrig += 1
                    last_trigger_time = tcall

                    # Add trigger time to dict
                    pos["trigger_time"] = last_trigger_time
                    pos["ntrig"] = ntrig

                    # Opto Trigger
                    if args.opto:
                        if random.random() < sham_perc:
                            logging.debug("Sham opto.")
                            stim_duration = 0
                            stim_intensity = 0
                            stim_frequency = 0
                        else:
                            stim_duration = duration
                            stim_intensity = intensity
                            stim_frequency = frequency

                        logging.debug("Triggering opto.")
                        opto_trigger_time = time.time()
                        opto_trigger_board.write(
                            f"<{stim_duration},{stim_intensity},{stim_frequency}>".encode()
                        )
                        pos["opto_duration"] = stim_duration
                        pos["opto_intensity"] = stim_intensity
                        pos["opto_frequency"] = stim_frequency
                        logging.debug(
                            f"Opto trigger time: {time.time()-opto_trigger_time:.5f}"
                        )

                    logging.debug("Triggering cameras.")
                    camera_trigger_time = time.time()
                    if args.highspeed:
                        if params["highspeed"]["type"] == "basler":
                            for _, cam_pipe in highspeed_cameras_pipes.items():
                                cam_pipe["send"].send(pos)

                        elif params["highspeed"]["type"] == "ximea":
                            pos["timestamp"] = tcall
                            publisher.send(json.dumps(pos).encode("utf-8"))
                        else:
                            logging.debug(f"No highspeed camera type specified.")
                            pass

                    logging.debug(
                        f"Camera trigger time: {time.time()-camera_trigger_time:.5f}"
                    )

                    # Stim Trigger
                    logging.debug("Triggering stim.")
                    stim_trigger_time = time.time()
                    if args.looming or args.grating:
                        stim_send.send(pos)
                    logging.debug(
                        f"Stim trigger time: {time.time()-stim_trigger_time:.5f}"
                    )

                    # Write data to csv
                    if args.opto:
                        logging.debug("Writing data to csv.")
                        csv_writer_time = time.time()
                        if write_header:
                            csv_writer.writerow(pos.keys())
                            write_header = False
                        csv_writer.writerow(pos.values())
                        csv_file.flush()
                        logging.debug(
                            f"CSV writer time: {time.time()-csv_writer_time:.5f}"
                        )

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received.")
        kill_event.set()
        logging.debug("Set kill event.")

        # Close all processes
        logging.debug("Closing all camera processes.")
        for cam in highspeed_cameras:
            cam.join()

        # Close all boards
        logging.debug("Closing all Arduino boards.")
        if args.opto:
            opto_trigger_board.close()

        if args.highspeed:
            # close the ximea camera
            if params["highspeed"]["type"] == "ximea":
                publisher.send(b"kill")
                ximea_camera_process.wait()

            # or the basler cameras
            elif params["highspeed"]["type"] == "basler":
                camera_trigger_board.write(b"0")
                camera_trigger_board.close()
            else:
                pass

        # Close CSV file
        logging.debug("Closing CSV file.")
        csv_file.close()

        logging.debug("Closing power supply.")
        ps.set_voltage(0)

        # copy all video files to new hdd
        # logging.debug("Copying video files to new hdd.")
        # old_folder = params["video_save_folder"]
        # new_folder = os.path.join(
        #     "/media/benyishay_la/8tb_data/videos/",
        #     os.path.basename(params["video_save_folder"]),
        # )
        # copy_files_with_progress(old_folder, new_folder)

        logging.info("Finished.")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(processName)s: %(asctime)s - %(message)s",
    )

    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--opto", action="store_true", default=False)
    parser.add_argument("--static", action="store_true", default=False)
    parser.add_argument("--looming", action="store_true", default=False)
    parser.add_argument("--grating", action="store_true", default=False)
    parser.add_argument("--highspeed", action="store_true", default=False)
    parser.add_argument("--debug", action="store_true", default=False)
    args = parser.parse_args()

    for arg in vars(args):
        logging.info(f"{arg}: {getattr(args, arg)}")

    # Start main function
    main(
        params_file="./data/params.toml",
        root_folder="/home/buchsbaum/mnt/DATA/Experiments/",
        args=args,
    )
