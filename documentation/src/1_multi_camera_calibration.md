# Braid Multi-camera calibration
The internal Braid multi-camera calibration involves several components and steps, and it generally follows the guide as outlined here:
<https://strawlab.github.io/strand-braid/braid_calibration.html>

I would recommend following the steps as described there, but I will try to write a similar explanation.

## Basic requirements
* A Python environment manager such as [**mamba**](https://mamba.readthedocs.io/en/latest/installation/mamba-installation.html) or [conda](https://conda.io/projects/conda/en/latest/user-guide/install/index.html).
* An installation of [**Octave**](https://wiki.octave.org/Octave_for_Debian_systems).

## Creating a Flydra environment
Many of the calibration tools rely on the old StrawLab `flydra` package. If nothing changed, the PC should already have a pre-existing one.
Otherwise, installation is pretty simple, and involves the following steps:
```
mamba env create -n flydra python=3.8
mamba activate flydra
pip install flydra_core flydra_analysis multicamselfcal
```

<div class="warning">
You must now use this environment whenever running this calibration for Braid.
</div>

## Acquiring Data
<div class="warning">
Room lights should be <b>off</b>.

It is also recomennded to not have the arena enclosure mounted, as it makes it easier and prevents reflections.
</div>

Run braid in another terminal using:
```
braid-run ~/braid-configs/1_laser_calibration.toml
```
- Make sure all camera are connected and working properly.
- Press the record button
- Move a laser pointer with a piece of tape on the lens throughtout the entire volume, even outside the arena tracking range.  
Don't move it too fast, to avoid false detections and errors.  
Turn the laser off occasionally.
- Do this for around 30 seconds, and then stop the recording.
- Shut down braid using ctrl-c in the terminal.

## Running MCSC on the dataset
### Convert `.braidz` to flydra `.h5` file
* Use the terminal to go the to folder where the `.braidz` file was saved -- should be `/home/buchsbaum/mnt/DATA/Experiments/Calibration`.
* Let's assume the filename is `20190924_161153.braidz`. Run the following commands:
```
BRAIDZ_FILE=20190924_161153.braidz
DATAFILE="$BRAIDZ_FILE.h5"
python ~/src/strand-braid/strand-braid-user/scripts/convert_braidz_to_flydra_h5.py --no-delete $BRAIDZ_FILE
```
This should convert the file to a type that can be handled by `flydra`.

### Run MultiCamSelfCal on data
* Run the following command to perform the calibration:
```
flydra_analysis_generate_recalibration --2d-data $DATAFILE --disable-kalman-objs $DATAFILE --undistort-intrinsics-yaml=$HOME/.config/strand-cam/camera_info  --run-mcsc --use-nth-observation=4
```
You can change the `use-nth-observation` to a higher number if calibration is taking too long - you generally want to aim for between 300 and 1000 points (although I found that less points is better, somehow.)

* Once the calibration is finished, you want to take a look at the output - you general want the `mean` and `std` values per-camera and on average to be ideally less than 0.5. If it's higher than 1, you should redo the calibration.
* If the reprojection errors are particulalry high, it sometimes help to take a look at the cameras while moving the laser to see if it's even detectd, or if there's some weird reflections throwing off the tracking.

### Convert the MCSC output to Braid
Use the following command:
```
flydra_analysis_calibration_to_xml ${DATAFILE}.recal/result > new-calibration-name.xml
```
Where `new-calibration-name` should be something more informative, like the filename of the `.braidz` file with `_laser_calibration` (`20190924_161153_laser_calibration.xml`).