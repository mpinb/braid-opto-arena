# Initial Camera Setup and Calibration

This guide outlines the process for setting up and calibrating Basler cameras using ROS camera calibration software instead of Braid's internal calibration tool.

## Camera Models
We use a mix of:
- Basler ace U acA800-510um
- Basler ace 2 a2A1920-51gmBAS

## Prerequisites
This guide assumes a clean Ubuntu installation. If using a pre-existing installation, you can skip the Installation step.

## Installation

1. Install ROS:
   Follow the guide at [ROS Noetic Installation for Ubuntu](http://wiki.ros.org/noetic/Installation/Ubuntu)

2. Install Pylon Camera software:
   Download and install [Pylon 6.2 for Linux x86 64-bit](https://www2.baslerweb.com/de/downloads/downloads-software/software-pylon-6-2-0-linux-x86-64bit-debian/)

   > **Warning**: While the `pylon-ros-camera` package requires Pylon 6.2, `Braid` itself requires Pylon 7.3. Make sure to reinstall Pylon 7.3 after finishing the calibration.

3. Install the pylon-ros-camera package:
   Follow instructions at [pylon-ros-camera GitHub repository](https://github.com/basler/pylon-ros-camera/tree/master)

## Preparation

1. Open Pylon Viewer to list all available cameras.
2. Launch two terminal windows and activate the `catkin` workspace in both:
   ```
   source ~/catkin_ws/devel.setup.bash
   ```
3. Remove the arena enclosure to allow more space for calibration board movement.

## Per-camera Calibration Procedure

### Camera Node Terminal

1. Navigate to `pylon-ros-camera/pylon-camera/config/` and open `default.yaml` in a text editor.
2. Change the `device_user_id` setting to the camera you want to calibrate.
3. Launch the camera node:
   ```
   roslaunch pylon_camera pylon_camera_node.launch
   ```

### Camera Calibrator Terminal

1. Launch the ROS camera_calibration app:
   ```
   rosrun camera_calibration cameracalibrator.py --size 8x6 --square 0.108 image:=/pylon_camera_node/raw_image camera:=/pylon_camera_node
   ```
   Adjust `size` and `square` parameters according to your calibration board (where `square` is in meters).

2. Move the calibration board around until all bars (X, Y, Size, and Skew) are green.
3. Press `CALIBRATE` and wait for completion.
4. Press `SAVE` to save the calibration file.
5. Rename the saved file (found at `/tmp/calibrationdata.tar.gz`) to `Basler-[camera_number]` and move it to `/home/buchsbaum/.config/strand-cam/camera_calibrations/`.

Repeat this process for all cameras in the setup.

## Format Calibrations

1. Navigate to `/home/buchsbaum/.config/strand-cam/camera_calibrations/`.
2. For each `tar.gz` file:
   - Extract the `ost.yaml` file.
   - Change the `camera_name` parameter to `Basler_[camera-number]`.
   - Rename the file to `basler_[camera-number].yaml`.
   - Move the file to `/home/buchsbaum/.config/strand-cam/camera_info/`.
   - If an older file with the same name exists, rename it to `basler-[camera-number].yaml.bak`.

## Next Steps

With the calibration complete, you can now proceed to calibrate the Braid tracking system using this data.