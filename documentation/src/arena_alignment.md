# Arena Alignment Guide for Braid

This guide outlines the process for aligning the arena using a laser pointer, which allows you to align tracked data to a desired frame-of-reference with (0,0,0) as the bottom center of the arena.

> **Note**: It is highly recommended to follow the official tutorial available at [Strand-Braid Documentation](https://strawlab.github.io/strand-braid/braid_calibration.html#align-your-new-calibration-using-a-gui).

## Table of Contents
1. [Preparation](#preparation)
2. [Data Collection](#data-collection)
3. [Data Processing](#data-processing)
4. [Arena Alignment](#arena-alignment)

## Preparation

1. Create a copy of `1_laser_calibration.toml` and rename it to `2_laser_align.toml`.

2. Open `2_laser_align.toml` and update the `cal_fname` value to the full path of the `.xml` file created in the previous calibration step.

3. Re-mount the arena enclosure.

> **Note**: It is preferable to perform this step with room lights off.

## Data Collection

1. Run Braid using the following command:
   ```bash
   braid-run ./braid-configs/2_laser_align.toml
   ```

2. Ensure all cameras are connected and start recording.

3. Use the laser pointer to outline the arena:
   - Move the pointer underneath the arena (pointing up) to define the bottom of the volume. Cover as much of the arena bottom as possible.
   - Trace the top perimeter of the arena. This will appear as a circle in the alignment GUI.
   - Track as much of the arena outline as possible for later use.

4. Once sufficient tracking data is collected, stop the recording and shut down Braid.

## Data Processing

Ensure you are in the `flydra` Mamba environment before proceeding.

1. Navigate to the folder containing the new `.braidz` file.

2. Convert the newly tracked data to `.h5` format:
   ```bash
   python ~/src/strand-braid/strand-braid-user/scripts/convert_braidz_to_flydra_h5.py --no-delete 20190924_161153.braidz
   ```
   Replace `20190924_161153.braidz` with your actual filename.

## Arena Alignment

1. Run the alignment GUI:
   ```bash
   flydra_analysis_calibration_align_gui --stim-xml ~/src/flydra/flydra_analysis/flydra_analysis/a2/sample_bowl.xml ${NEW_TRACKED_DATA}
   ```
   Replace `${NEW_TRACKED_DATA}` with your newly created `.h5` file.

   > **Note**: The `sample_bowl.xml` file is used to define the arena parameters. It should already fit the current arena setup.

2. Complete the alignment process using the GUI.

3. Save the alignment as an `.xml` file.

4. Use this new `.xml` file for all subsequent Braid configuration `.toml` files.

This completes the arena alignment process for Braid.