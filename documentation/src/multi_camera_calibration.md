# Braid Multi-camera Calibration Guide

This guide outlines the process for calibrating multiple cameras in the Braid system. While it follows the official guide available at [Strand-Braid Documentation](https://strawlab.github.io/strand-braid/braid_calibration.html), this document provides a simplified explanation of the steps involved.

## Table of Contents
1. [Basic Requirements](#basic-requirements)
2. [Creating a Flydra Environment](#creating-a-flydra-environment)
3. [Acquiring Calibration Data](#acquiring-calibration-data)
4. [Running MCSC on the Dataset](#running-mcsc-on-the-dataset)
   - [Converting .braidz to Flydra .h5 File](#converting-braidz-to-flydra-h5-file)
   - [Running MultiCamSelfCal on Data](#running-multicamselfcal-on-data)
   - [Converting MCSC Output to Braid](#converting-mcsc-output-to-braid)

## Basic Requirements

- Python environment manager: [Mamba](https://mamba.readthedocs.io/en/latest/installation/mamba-installation.html) (recommended) or [Conda](https://conda.io/projects/conda/en/latest/user-guide/install/index.html)
- [Octave](https://wiki.octave.org/Octave_for_Debian_systems)

## Creating a Flydra Environment

Many calibration tools rely on the StrawLab `flydra` package. If a pre-existing environment is not available, follow these steps to create one:

```bash
mamba env create -f flydra_env.yaml # Using the file provided in the root folder of this project
mamba activate flydra-env
```

or

```bash
mamba env create -n flydra-env python=3.8
mamba activate flydra
pip install flydra_core flydra_analysis multicamselfcal
```

> **Warning**: Always use this environment when running calibrations for Braid.

## Acquiring Calibration Data

> **Important**: 
> - Room lights should be **off**.
> - It's recommended to remove the arena enclosure to facilitate movement and prevent reflections.

1. Run Braid in a separate terminal:
   ```bash
   braid-run ~/braid-configs/1_laser_calibration.toml
   ```

2. Ensure all cameras are connected and working properly.

3. Press the record button.

4. Move a laser pointer (with a piece of tape on the lens) throughout the entire volume:
   - Cover areas even outside the arena tracking range.
   - Move slowly to avoid false detections and errors.
   - Occasionally turn the laser off.

5. Continue for approximately 30 seconds, then stop the recording.

6. Shut down Braid using `Ctrl+C` in the terminal.

## Running MCSC on the Dataset

### Converting .braidz to Flydra .h5 File

1. Navigate to the folder containing the `.braidz` file (typically `/home/buchsbaum/mnt/DATA/Experiments/Calibration`).

2. Run the following commands, replacing `20190924_161153.braidz` with your actual filename:

   ```bash
   BRAIDZ_FILE=20190924_161153.braidz
   DATAFILE="$BRAIDZ_FILE.h5"
   python ~/src/strand-braid/strand-braid-user/scripts/convert_braidz_to_flydra_h5.py --no-delete $BRAIDZ_FILE
   ```

### Running MultiCamSelfCal on Data

1. Execute the calibration command:

   ```bash
   flydra_analysis_generate_recalibration --2d-data $DATAFILE --disable-kalman-objs $DATAFILE --undistort-intrinsics-yaml=$HOME/.config/strand-cam/camera_info  --run-mcsc --use-nth-observation=4
   ```

   > **Note**: Adjust `use-nth-observation` if calibration takes too long. Aim for 300-1000 points (fewer points often yield better results).

2. Review the output:
   - Ideal `mean` and `std` values per camera and on average: < 0.5
   - If values are > 1, consider redoing the calibration
   - For high reprojection errors, check camera detection and potential reflections

### Converting MCSC Output to Braid

Generate the XML file using:

```bash
flydra_analysis_calibration_to_xml ${DATAFILE}.recal/result > new-calibration-name.xml
```

Replace `new-calibration-name` with an informative name, e.g., `20190924_161153_laser_calibration.xml`.

This completes the Braid multi-camera calibration process.