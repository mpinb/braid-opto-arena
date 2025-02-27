# Braid Opto Arena

Braid Opto Arena is a Python-based project for controlling optogenetic stimulation in response to real-time tracking data from the [Braid](https://github.com/strawlab/strand-braid) system. It integrates visual stimuli presentation, high-speed camera control, and optogenetic triggering based on configurable conditions.

## Table of Contents

- [Project Structure](#project-structure)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Components](#components)

## Project Structure

```
braid-opto-arena/
├── notebooks/
├── src/
│   ├── devices/
│   │   ├── opto_trigger.py
│   │   └── power_supply.py
│   ├── stimuli/
│   │   ├── visual_controller.py
│   │   └── visual_stimuli.py
│   ├── braid_proxy.py
│   ├── config_manager.py
│   ├── csv_writer.py
│   ├── fly_heading_tracker.py
│   ├── messages.py
│   ├── process_manager.py
│   └── trigger_handler.py
├── config.yaml
└── main.py
```

## Installation

1. Clone the repository:

  ```
  git clone https://github.com/your-username/braid-opto-trigger.git
  cd braid-opto-arena
  ```

2. Create a virtual environment and activate it (**mamba**/conda):

  ```
  mamba env create -f environment.yaml
  mamba activate braid-opto-arena-env
  ```

## Configuration

The project uses a YAML configuration file (`config.yaml`) to set various parameters. Make sure to adjust the configuration file according to your setup before running the program.

Key configuration sections include:

- Hardware settings (Arduino, power supply)
- Braid connection details
- Optogenetic light parameters
- Visual stimuli settings
- Trigger conditions

## Usage

To run the main program:

```
python main.py --config config.yaml
```

Additional command-line arguments:

- `--debug`: Run without active Braid tracking

For running the visual stimuli controller separately:

```
python src/stimuli/visual_controller.py --config_file config.yaml --braid_folder /path/to/braid/folder
```

# Configuration Options

## Command Line Usage

The configuration can be modified at runtime using the `--set` flag. The general format is:

```bash
python main.py --set key.subkey=value
```

Multiple settings can be modified using multiple `--set` flags:

```bash
python main.py --set experiment.time_limit=48 --set trigger.radius.distance=0.03
```

## Available Configuration Options

### Braid System Settings

```bash
# Base URL for the Braid system
--set braid.url=http://127.0.0.1

# Event and control ports
--set braid.event_port=8397
--set braid.control_port=32935
```

### Experiment Settings

```bash
# Duration of experiment in hours (use 0 for unlimited)
--set experiment.time_limit=24

# Base paths for experiment data and videos
--set experiment.exp_base_path=/path/to/experiments
--set experiment.video_base_path=/path/to/videos
```

### Trigger Settings

```bash
# Trigger zone type (can be "box" or "radius")
--set trigger.zone_type=radius

# Box trigger settings (in meters)
--set trigger.box.x=[-0.058,0.033]
--set trigger.box.y=[-0.024,0.066]
--set trigger.box.z=[0.10,0.25]

# Radius trigger settings
--set trigger.radius.center=[0,0]      # x,y coordinates in mm
--set trigger.radius.distance=0.025     # distance from center in meters
--set trigger.radius.z=[0.05,0.25]     # z-axis bounds in meters

# Timing parameters (in seconds)
--set trigger.min_trajectory_time=1.0
--set trigger.min_trigger_interval=5.0
```

### Optogenetic Light Settings

```bash
# Enable/disable optogenetic light
--set optogenetic_light.enabled=true

# Light parameters
--set optogenetic_light.duration=300       # milliseconds
--set optogenetic_light.intensity=255      # absolute PWM value
--set optogenetic_light.frequency=0        # Hz
--set optogenetic_light.sham_trial_percentage=10
```

### Hardware Settings

```bash
# Arduino settings
--set hardware.arduino.port=/dev/optotrigger
--set hardware.arduino.baudrate=115200

# Backlight settings
--set hardware.backlight.port=/dev/powersupply
--set hardware.backlight.voltage=24
--set hardware.backlight.baudrate=9600

# Lens driver settings
--set hardware.lensdriver.port=/dev/optotune_ld
```

### High-Speed Camera Settings

```bash
# Enable/disable high-speed camera
--set high_speed_camera.enabled=false

# Camera configuration
--set high_speed_camera.type=ximea
--set high_speed_camera.pre_trigger_record_time=0.5     # seconds
--set high_speed_camera.post_trigger_record_time=1.5    # seconds
--set high_speed_camera.framerate=500                   # fps
--set high_speed_camera.exposure_time=2000             # microseconds
```

### Visual Stimuli Settings

```bash
# Enable/disable visual stimuli
--set visual_stimuli.enabled=true
--set visual_stimuli.refresh_rate=60    # Hz

# Static stimulus
--set visual_stimuli.stimuli[0].type=static
--set visual_stimuli.stimuli[0].image=random
--set visual_stimuli.stimuli[0].enabled=true

# Looming stimulus
--set visual_stimuli.stimuli[1].type=looming
--set visual_stimuli.stimuli[1].enabled=false
--set visual_stimuli.stimuli[1].start_radius=5
--set visual_stimuli.stimuli[1].end_radius=128
--set visual_stimuli.stimuli[1].duration=300
--set visual_stimuli.stimuli[1].position_type=closed-loop
--set visual_stimuli.stimuli[1].fixed_position=[400,300]

# Grating stimulus
--set visual_stimuli.stimuli[2].type=grating
--set visual_stimuli.stimuli[2].enabled=false
--set visual_stimuli.stimuli[2].bar_width=20
--set visual_stimuli.stimuli[2].frequency=2
--set visual_stimuli.stimuli[2].direction=right   # can be 'left' or 'right'
```

### ZMQ Communication Settings

```bash
--set zmq.port=5556
```

### Logging Settings

```bash
--set logging.trigger_data_file=trigger_data.csv
--set logging.log_level=INFO
```

## Examples

Here are some common use cases:

1. Change experiment duration and trigger settings:

  ```bash
  python main.py --set experiment.time_limit=48 --set trigger.radius.distance=0.03
  ```

2. Modify camera settings:

  ```bash
  python main.py --set high_speed_camera.enabled=true --set high_speed_camera.framerate=1000
  ```

3. Update optogenetic light parameters:

  ```bash
  python main.py --set optogenetic_light.duration=500 --set optogenetic_light.intensity=200
  ```

4. Change hardware ports:

  ```bash
  python main.py --set hardware.arduino.port=/dev/ttyUSB0 --set hardware.backlight.port=/dev/ttyUSB1
  ```

## Notes

- Boolean values should be specified as `true` or `false` (lowercase)
- Lists should be specified in square brackets with comma separation: `[value1,value2]`
- String values don't need quotes unless they contain special characters
- Numbers can be integers or floating-point values

## Components

### Main Controller (`main.py`)

The main script that orchestrates the entire system. It initializes all components, manages processes, and handles the main loop for triggering optogenetic stimulation based on Braid data.

### Braid Proxy (`braid_proxy.py`)

Handles the connection to the Braid system and parses incoming data chunks.

### Config Manager (`config_manager.py`)

Manages the loading and access of configuration parameters from the YAML file.

### CSV Writer (`csv_writer.py`)

Handles writing data to CSV files for logging and analysis.

### Fly Heading Tracker (`fly_heading_tracker.py`)

Tracks the heading of flies based on velocity data from Braid.

### Messages (`messages.py`)

Implements a Publisher-Subscriber pattern for inter-process communication using ZeroMQ.

### Process Manager (`process_manager.py`)

Manages the starting and stopping of various subprocesses, including the visual stimuli controller and camera processes.

### Trigger Handler (`trigger_handler.py`)

Handles the logic for when to trigger optogenetic stimulation based on configured conditions.

### Opto Trigger (`opto_trigger.py`)

Controls the optogenetic stimulation hardware via serial communication with an Arduino.

### Power Supply (`power_supply.py`)

Interfaces with the RS PRO 3000/6000 Series programmable power supply for controlling backlighting.

### Visual Controller (`visual_controller.py`)

Controls the display of visual stimuli, including static images, looming stimuli, and gratings.

### Visual Stimuli (`visual_stimuli.py`)

The `visual_stimuli.py` file defines various visual stimuli classes used in the project. It provides a flexible structure for creating and managing different types of visual stimuli.

#### Key Classes and Methods

1. `Stimulus` (Abstract Base Class)

  - `__init__(self, config)`: Initializes the stimulus with a configuration dictionary.
  - `update(self, screen, time_elapsed)`: Abstract method to update the stimulus on the screen.

2. `StaticImageStimulus`

  - `__init__(self, config)`: Initializes the static image stimulus.
  - `_create_surface(self, config)`: Creates the surface based on the configuration.
  - `_load_image(self, image_path)`: Loads an image from a file.
  - `_generate_random_stimuli(self, width, height, ratio)`: Generates a random stimulus pattern.
  - `update(self, screen, time_elapsed)`: Blits the static image onto the screen.

3. `LoomingStimulus`

  - `__init__(self, config)`: Initializes the looming stimulus with configurable parameters.
  - `_get_value(self, value, min_val, max_val)`: Helper method to get random or fixed values.
  - `generate_natural_looming(self, max_radius, duration, l_v, distance_from_screen, hz)`: Generates a natural looming pattern.
  - `generate_exponential_looming(self, max_radius, duration, hz)`: Generates an exponential looming pattern.
  - `start_expansion(self, heading_direction)`: Starts the expansion of the looming stimulus.
  - `update(self, screen, time_elapsed)`: Updates the looming stimulus on the screen.
  - `get_trigger_info(self)`: Returns information about the current state of the stimulus.

4. `GratingStimulus`

  - `__init__(self, config)`: Initializes the grating stimulus.
  - `update(self, screen, time_elapsed)`: Updates the grating stimulus on the screen (currently not implemented).

#### Adding New Stimulus Types

To add a new type of stimulus:

1. Create a new class that inherits from the `Stimulus` base class.
2. Implement the `__init__` method to initialize your stimulus with the necessary parameters.
3. Implement the `update` method to define how your stimulus should be drawn and updated on the screen.
4. (Optional) Add any additional methods specific to your stimulus type.

Example of adding a new stimulus type:

```python
class RotatingShapeStimulus(Stimulus):
    def __init__(self, config):
        super().__init__(config)
        self.shape = config.get("shape", "circle")
        self.color = pygame.Color(config.get("color", "red"))
        self.size = config.get("size", 50)
        self.rotation_speed = config.get("rotation_speed", 1)
        self.angle = 0

    def update(self, screen, time_elapsed):
        self.angle += self.rotation_speed * time_elapsed / 1000
        center = (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2)

        if self.shape == "circle":
            pygame.draw.circle(screen, self.color, center, self.size)
        elif self.shape == "square":
            rect = pygame.Rect(0, 0, self.size, self.size)
            rect.center = center
            rotated_surface = pygame.Surface((self.size, self.size), pygame.SRCALPHA)
            pygame.draw.rect(rotated_surface, self.color, (0, 0, self.size, self.size))
            rotated_surface = pygame.transform.rotate(rotated_surface, self.angle)
            screen.blit(rotated_surface, rotated_surface.get_rect(center=center))
```

To use the new stimulus type:

1. Add it to the `STIMULUS_TYPES` dictionary in `visual_controller.py`:

```python
STIMULUS_TYPES = {
    "static": StaticImageStimulus,
    "looming": LoomingStimulus,
    "grating": GratingStimulus,
    "rotating_shape": RotatingShapeStimulus,  # Add this line
}
```

1. Update your configuration file to include the new stimulus type:

```yaml
stimuli:
  - type: rotating_shape
    enabled: true
    shape: square
    color: blue
    size: 40
    rotation_speed: 2
```

By following this pattern, you can easily extend the visual stimuli system to include new types of stimuli as needed for your experiments.
