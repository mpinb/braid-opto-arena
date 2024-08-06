# Arena Alignment
In this step, outline the arena using the laser pointer, so later we can align the tracked data to a desired frame-of-reference, with (0,0,0) as the bottom center of the arena. Again, it is highly recommended to use the tutorial from here:
<https://strawlab.github.io/strand-braid/braid_calibration.html#align-your-new-calibration-using-a-gui>

* First, make a copy of `1_laser_calibration.toml`, and rename to `2_laser_align.toml`.
* Open `2_laser_align.toml` and update the `cal_fname` value to the full path of the `.xml` file we created in the previous step.
* Re-mount the arena enclosure. It is preferable for the room lights to be off for this step as well.
* Run braid using:
```
braid-run ./braid-configs/2_laser_align.toml
```
* Make sure all cameras are connected, and start recording.
* Use the laser pointer to outline the arena.
    * I usually do this by moving the pointer underneath the arena (pointing up), which then acts as the bottom of the volume. Make sure to cover as much of the arena bottom as possible.
    * Then, move the pointer along the top perimeter of the arena. This will show up as a circle in the alignment GUI.
    * In general, use to pointer to track as much of the arena outline that can be useful later.

* After you think you got enough tracking data, stop the recording and shut down `braid`.

Now we must again make sure we are in the `flydra` mamba environment, and: (1) convert the newly tracked data to `.h5`, and (2) run the alignment GUI.
1. Same as before, go to the folder where the new `.braidz` file was saved and run:
```
python ~/src/strand-braid/strand-braid-user/scripts/convert_braidz_to_flydra_h5.py --no-delete 20190924_161153.braidz
```
2. Run the alignment GUI:
```
flydra_analysis_calibration_align_gui --stim-xml ~/src/flydra/flydra_analysis/flydra_analysis/a2/sample_bowl.xml ${NEW_TRACKED_DATA}
```

You can use `sample_bowl.xml` to define the arena parameters, although it should already fit our current arena.

After finishing the alignment, save it as `.xml`, and we use it for all the following braid-config `.toml` files.