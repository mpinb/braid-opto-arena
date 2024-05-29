# BraidTrigger
A software to control optogenetic activation, visual stimuli, and high-speed camera acquisition synchronized with the [*Braid*](https://github.com/strawlab/strand-braid/) tracking program.

## Description
The main script is `BraidTrigger.py`, which initializes all required components (visual stimuli, optogenetic control, high speed camera) and starts looping over data incoming from *Braid*.

`BraidTrigger.py` accepts the following command-line arguments:
- `opto` - use optogenetic stimulus (boolean).
- `static` - display static background stimuli (boolean).
- `looming` - display closed-loop looming stimulus (boolean).
- `gratin` - display a rotating grating (boolean).
- `highspeed` - record highspeed videos (boolean).
- `debug` - print extra infromation.
- `dry-run` (TODO) - run script without running Braid.

The main script performs the following steps:
1. load the `params.toml` file, which contains all the currect experiments parameters.
2. check if braid is running, but looking for a `.braid` folder in a predefined location.
3. startup the arena IR backlighting (currently by simply connecting to an RS power supply and setting the voltage to maximum.)
4. connect to `braid`.
5. initialize the appropriate highspeed camera, as defined in the `params.toml` file.
6. initialize the stimuli.
7. get basic trigger parameters.
8. start looping over incoming `braid` data, and check if it's appropriate to trigger.

## Sub-modules
TODO

## Documentation
TODO
