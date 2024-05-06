import argparse
import numpy as np


def main(args):
    area_lens = np.pi * (args.lens_diameter / 2) ** 2
    area_sensor = args.sensor_width * args.sensor_height
    ratio_usable = min((area_lens / area_sensor, 1))
    print(f"Usable area ratio: {ratio_usable:.2f}")
    width_usable = int(args.sensor_width * np.sqrt(ratio_usable))
    height_usable = int(args.sensor_height * np.sqrt(ratio_usable))
    mp_usable = width_usable * height_usable / 1e6
    print(f"Usable resolution: {width_usable}x{height_usable} ({mp_usable:.2f} MP)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument()
    args = parser.parse_args()
