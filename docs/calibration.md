# Multi-Camera Calibration Guide

- [Multi-Camera Calibration Guide](#multi-camera-calibration-guide)
  - [1. Introduction](#1-introduction)
  - [2. Prerequisites](#2-prerequisites)
    - [Software](#software)
    - [Hardware](#hardware)
    - [Setup](#setup)
  - [3. Intrinsic Calibration](#3-intrinsic-calibration)
    - [3.1 Preparation](#31-preparation)
    - [3.2 Software Setup](#32-software-setup)
    - [3.3 Calibration Process](#33-calibration-process)
    - [3.4 Data Management](#34-data-management)
  - [4. Extrinsic Calibration](#4-extrinsic-calibration)
    - [4.1 Preparation](#41-preparation)
    - [4.2 Data Collection](#42-data-collection)
    - [4.3 Software Setup](#43-software-setup)
    - [4.4 Data Processing](#44-data-processing)
    - [4.5 Arena Alignment](#45-arena-alignment)
    - [4.6 Final Configuration](#46-final-configuration)
  - [5. Troubleshooting](#5-troubleshooting)
  - [6. Validation](#6-validation)
  - [7. Glossary](#7-glossary)
  - [8. References](#8-references)

## 1. Introduction

Camera calibration is a crucial step in setting up a multi-camera system, especially after any physical changes to the setup (e.g., moving or rotating cameras). This guide will walk you through the process of performing a full calibration procedure using the `braid` system and additional tools.

The calibration process consists of two main parts:

1. Intrinsic calibration: Determines each camera's internal parameters.
2. Extrinsic calibration: Establishes the spatial relationships between cameras.

## 2. Prerequisites

Before beginning the calibration process, ensure you have the following:

### Software

- [Basler Pylon](https://www2.baslerweb.com/de/downloads/downloads-software/software-pylon-6-3-0-linux-x86-64bit-debian/) (version 6.3.0)
- [ROS Noetic](https://wiki.ros.org/noetic/Installation/Ubuntu)
- [pylon-ROS-camera package](https://github.com/basler/pylon-ros-camera/tree/master)

### Hardware

- Multi-camera setup
- Calibration board (8x6 checkerboard pattern, 25mm square size)
- Large white plexiglass diffuser
- Thorlabs posts
- Backlighting power supply

### Setup

- Ensure all cameras are connected and recognized by the system
- Verify that the calibration board is in good condition and matches the specified dimensions

## 3. Intrinsic Calibration

### 3.1 Preparation

1. Remove the entire arena enclosure.
2. Place a large white plexiglass diffuser on the Thorlabs posts.
3. Turn on the backlighting power supply to maximum.

   > Note: The diffuser and backlighting help create optimal lighting conditions for calibration, ensuring clear visibility of the calibration pattern.

### 3.2 Software Setup

1. Open two terminals and in each run:

   ```sh
   source ~/catkin_ws/devel/setup.bash
   ```

   This allows you to run (a) a Basler ROS camera node and (b) the camera calibrator using the Pylon camera driver.

2. Open the following in separate file explorers:
   - `/home/buchsbaum/catkin_ws/src/pylon-ros-camera/pylon_camera/config/`
   - `/tmp/`
   - `/home/buchsbaum/ros_camera_calibration`

3. Open Pylon Viewer to see a list of all available cameras.

### 3.3 Calibration Process

Repeat the following steps for each camera:

1. Open `/home/buchsbaum/catkin_ws/src/pylon-ros-camera/pylon_camera/config/default.yaml`.
2. Change the `device_user_id` to match one of the cameras listed in Pylon Viewer. Save the file.
3. In one terminal, run:

   ```sh
   roslaunch pylon_camera pylon_camera_node.launch
   ```

4. In the other terminal, run:

   ```sh
   rosrun camera_calibration cameracalibrator.py --size 8x6 --square 0.025 image:=/pylon_camera_node/image_raw camera:=/pylon_camera_node
   ```

   > Note: Adjust `--size` and `--square` parameters if using a different calibration board.

5. Move the calibration board in front of the camera:
   - Cover different distances from the camera
   - Fill the entire frame
   - Tilt the board at various angles
   - Continue until all bars in the calibration application turn green

6. Click the `Calibrate` button and wait for the process to complete.

### 3.4 Data Management

1. Once calibration is finished, find the `calibrationdata.tar.gz` file in `/tmp/`.
2. Copy this file to `/home/buchsbaum/ros_camera_calibration/`.
3. Rename the file to include the camera number (e.g., `40154015.tar.gz`).
4. Close both terminal windows (Ctrl-C) to shut down the Basler node and camera calibrator.

After calibrating all cameras:

1. Navigate to `/home/buchsbaum/ros_camera_calibration/` in the terminal.
2. Run the processing script:

   ```sh
   python ./process_files.py
   ```

   This processes and copies all files to the correct position for Braid to use them.

## 4. Extrinsic Calibration

Extrinsic calibration determines the spatial relationships between cameras in your multi-camera setup. This process involves recording an infrared laser pointer's movement and processing the data using specialized software.

### 4.1 Preparation

1. Ensure the backlighting is turned off.
2. Prepare an infrared (IR) laser pointer:
   - Cover the pointer with double-sided tape or a small diffuser to create a more visible spot.

### 4.2 Data Collection

1. Navigate to the Braid configuration directory:

   ```sh
   cd ~/braid-configs/
   ```

2. Run Braid with the laser calibration configuration:

   ```sh
   braid-run ./1_laser_calibration.toml
   ```

3. Record laser pointer movement:
   - Move the IR laser pointer inside and outside the tracking volume.
   - Occasionally turn the laser pointer on and off.
   - Continue until you believe you've captured sufficient data.

4. Stop the recording. The data will be saved as a `.braidz` file in:

   ```sh
   /home/buchsbaum/mnt/DATA/Experiment/Calibration
   ```

### 4.3 Software Setup

Ensure you have the following software installed:

1. Octave (if not already installed):

   ```sh
   sudo apt-add-repository ppa:octave/stable
   sudo apt-get update
   sudo apt-get install octave
   ```

2. Flydra environment:

   ```sh
   mamba env create -f flydra_env.yaml
   mamba activate flydra
   ```

3. Clone necessary repositories:

   ```sh
   cd ~/src/
   git clone https://github.com/strawlab/flydra.git
   git clone https://github.com/strawlab/MultiCamSelfCal
   git clone https://github.com/strawlab/strand-braid/
   ```

### 4.4 Data Processing

1. Navigate to the Calibration folder:

   ```sh
   cd /home/buchsbaum/mnt/DATA/Experiment/Calibration
   ```

2. Convert the `.braidz` file to `.h5` format:

   ```sh
   BRAIDZ_FILE=your_file_name.braidz
   DATAFILE="$BRAIDZ_FILE.h5"
   python ~/src/strand-braid/strand-braid-user/scripts/convert_braidz_to_flydra_h5.py --no-delete $BRAIDZ_FILE
   ```

3. Run MultiCamSelfCal on the data:

   ```sh
   flydra_analysis_generate_recalibration --2d-data $DATAFILE --disable-kalman-objs $DATAFILE --undistort-intrinsics-yaml=$HOME/.config/strand-cam/camera_info  --run-mcsc --use-nth-observation=4
   ```

   Note: Increase `--use-nth-observation` value to downsample data if needed.

4. Check the output for reprojection errors:
   - Errors should be below 1, ideally less than 0.5.
   - If errors are high (>1.0), re-record the tracking data and try again.

5. Convert the calibration to Braid-compatible format:

   ```sh
   flydra_analysis_calibration_to_xml ${DATAFILE}.recal/result > new_calibration.xml
   ```

### 4.5 Arena Alignment

1. Mount the arena about 15cm above the bottom to allow space for laser pointer movement.

2. Update the `2_laser_align.toml` file:
   - Change `cal_fname` to the full path of your new calibration file.

3. Run Braid with the updated configuration:

   ```sh
   braid-run ~/braid-configs/2_laser_align.toml
   ```

4. Record laser pointer movement:
   - Move the laser back-and-forth below the arena (pointing up) to track the bottom.
   - Move it inside the arena around the top circle for outline tracking.

5. Stop the recording and convert the new `.braidz` file to `.h5` format as before.

6. Run the calibration alignment GUI:

   ```sh
   flydra_analysis_calibration_align_gui --stim-xml ~/src/flydra/flydra_analysis/flydra_analysis/a2/sample_bowl.xml your_new_file.braidz.h5
   ```

7. In the GUI:
   - Scale the tracked points (usually down to around 0.1).
   - Adjust values until points align with the arena dimensions.
   - Save the aligned calibration as an XML file (e.g., `20240910_calibration_aligned.xml`).

### 4.6 Final Configuration

1. Update all relevant Braid configuration files (3, 4, 5) with the path to your new aligned calibration file.

2. Verify the calibration:
   - Use Braid configuration file #3 to perform basic laser tracking.
   - Check for proper opto/looming triggering.

## 5. Troubleshooting

[Add troubleshooting steps specific to extrinsic calibration]

## 6. Validation

[Add validation steps for the entire calibration process]

## 7. Glossary

- Extrinsic calibration: Process of determining the spatial relationship between multiple cameras.
- BRAIDZ file: A file format used by the Braid system to store recorded tracking data.
- MultiCamSelfCal: A tool for calibrating multiple cameras using correspondences between images.

## 8. References

- [Strand-braid Documentation](https://github.com/strawlab/strand-braid/)
- [Flydra Documentation](https://github.com/strawlab/flydra)
- [MultiCamSelfCal Repository](https://github.com/strawlab/MultiCamSelfCal)
