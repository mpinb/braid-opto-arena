import cv2
import numpy as np
import pandas as pd
import math
import os
import argparse
import sys
import matplotlib.pyplot as plt


def draw_debug_visualization(img, center_x, center_y, spot_x, spot_y, heading_rad):
    # Create a color debug image
    debug_img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    # Draw center point
    cv2.circle(debug_img, (int(center_x), int(center_y)), 5, (0, 0, 255), -1)

    # Draw detected spot center
    cv2.circle(debug_img, (int(spot_x), int(spot_y)), 5, (0, 255, 0), -1)

    # Draw line from center to spot
    cv2.line(
        debug_img,
        (int(center_x), int(center_y)),
        (int(spot_x), int(spot_y)),
        (255, 0, 0),
        2,
    )

    # Add text with angle
    text = f"Angle: {heading_rad:.2f} rad"
    cv2.putText(debug_img, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    return debug_img


def create_heading_plot(df, output_path):
    plt.figure(figsize=(12, 6))
    df["filename_as_int"] = df["filename"].str.extract(r"(\d+)").astype(int)

    # sort by filename_as_int
    df = df.sort_values("filename_as_int")
    plt.scatter(df["filename"], df["heading_rad"], color="blue", alpha=0.6)
    plt.plot(df["filename"], df["heading_rad"], color="gray", alpha=0.3, linestyle="--")

    plt.title("Heading Angles by Image")
    plt.xlabel("Pixel position")
    plt.ylabel("Heading (radians)")

    # Rotate x-axis labels for better readability
    plt.xticks(rotation=45, ha="right")

    # Add horizontal lines at π and -π for reference
    plt.axhline(y=np.pi, color="r", linestyle=":", alpha=0.3, label="π")
    plt.axhline(y=-np.pi, color="r", linestyle=":", alpha=0.3, label="-π")
    plt.axhline(y=0, color="k", linestyle=":", alpha=0.3, label="0")

    plt.grid(True, alpha=0.3)
    plt.legend()

    # Adjust layout to prevent label cutoff
    plt.tight_layout()

    # Save the plot
    plt.savefig(output_path)
    plt.close()


def calculate_heading(image_path, debug=False):
    # Read the image in grayscale
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)

    if img is None:
        raise ValueError(f"Could not read image: {image_path}")

    # Get image dimensions
    height, width = img.shape
    center_x, center_y = width // 2, height // 2

    # Find all white pixels
    white_pixels = np.where(img > 128)  # Threshold to find white pixels
    if len(white_pixels[0]) == 0:
        raise ValueError(f"No white spot found in image: {image_path}")

    # Calculate centroid using mean of white pixel coordinates
    spot_y = np.mean(white_pixels[0])
    spot_x = np.mean(white_pixels[1])

    # Calculate relative position from center
    dx = spot_x - center_x
    dy = -(spot_y - center_y)  # Negative because y increases downward in images

    # Calculate heading using arctan2 (result in radians)
    heading_rad = math.atan2(dy, dx)

    if debug:
        # Create debug visualization
        debug_img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        # Draw center point
        cv2.circle(debug_img, (int(center_x), int(center_y)), 5, (0, 0, 255), -1)

        # Draw detected spot center
        cv2.circle(debug_img, (int(spot_x), int(spot_y)), 5, (0, 255, 0), -1)

        # Draw line from center to spot
        cv2.line(
            debug_img,
            (int(center_x), int(center_y)),
            (int(spot_x), int(spot_y)),
            (255, 0, 0),
            2,
        )

        # Add text with angle
        text = f"Angle: {heading_rad:.2f} rad"
        cv2.putText(
            debug_img, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2
        )

        # Save debug image
        debug_dir = os.path.join(os.path.dirname(image_path), "debug")
        os.makedirs(debug_dir, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(image_path))[0]
        debug_path = os.path.join(debug_dir, f"{base_name}_debug.jpg")
        cv2.imwrite(debug_path, debug_img)

    return heading_rad


def process_images(directory, debug=False):
    # Prepare data storage
    results = []

    # Process each image
    for filename in sorted(os.listdir(directory)):
        if filename.lower().endswith((".jpg", ".jpeg")):
            # Get file name without extension
            name = os.path.splitext(filename)[0]

            try:
                # Calculate heading
                full_path = os.path.join(directory, filename)
                heading = calculate_heading(full_path, debug)

                # Store results
                results.append({"pixel": name, "heading_rad": heading})
                print(f"Processed {filename}: {heading:.2f} rad")
            except Exception as e:
                print(f"Error processing {filename}: {str(e)}")

    # Create DataFrame and save to CSV
    if results:
        df = pd.DataFrame(results)
        csv_path = os.path.join(directory, "headings.csv")
        df.to_csv(csv_path, index=False)
        print(f"\nResults saved to {csv_path}")

        if debug:
            # Create and save the heading plot
            debug_dir = os.path.join(directory, "debug")
            os.makedirs(debug_dir, exist_ok=True)
            plot_path = os.path.join(debug_dir, "heading_plot.png")
            create_heading_plot(df, plot_path)
            print(f"Debug visualizations saved in {debug_dir}")

        return df
    else:
        print("No images were processed successfully")
        return None


def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Calculate headings for white spots in images"
    )
    parser.add_argument("directory", help="Directory containing the JPEG images")
    parser.add_argument(
        "--debug", action="store_true", help="Generate debug visualizations"
    )

    # Parse arguments
    args = parser.parse_args()

    # Check if directory exists
    if not os.path.isdir(args.directory):
        print(f"Error: Directory '{args.directory}' does not exist")
        sys.exit(1)

    # Process the images
    try:
        process_images(args.directory, args.debug)
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
