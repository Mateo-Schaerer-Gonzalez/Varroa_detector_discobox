"""Manual smoke test: draw zones parsed from coordinates1.txt on the sample image."""
import sys
from pathlib import Path
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2

from classes.zones import Zone

SCRIPT_DIR = Path(__file__).resolve().parent
coord_path = SCRIPT_DIR / "coords_yolo.txt"

def convert_yolo_to_coords(input_file, output_file, image_path):
    """Convert YOLOv8 polygon format bounding boxes to pixel coordinates (x1, y1, x2, y2).
    
    Args:
        input_file (str): Path to the input file with YOLO format bounding boxes.
        output_file (str): Path to save the output file with pixel coordinates.
        image_path (str): Path to the image to get dimensions for conversion.
    
    Output format:
        class_id x1 y1 x2 y2  (pixel coordinates)
    """
    # Load image using cv2
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Image not found or unable to open: {image_path}")
    
    img_height, img_width = img.shape[:2]
    print(f"Image size: {img_width}x{img_height}")

    with open(input_file, 'r') as f_in, open(output_file, 'w') as f_out:
        for line in f_in:
            parts = line.strip().split()
            if len(parts) != 9:
                print(f"Skipping invalid line (expected 9 elements): {line.strip()}")
                continue

            class_id = parts[0]
            coords = list(map(float, parts[1:]))

            xs = coords[0::2]
            ys = coords[1::2]

            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)

            # Convert normalized coordinates to pixel coordinates
            x1_px = min_x * img_width
            y1_px = min_y * img_height
            x2_px = max_x * img_width
            y2_px = max_y * img_height

            f_out.write(f"{class_id} {x1_px:.2f} {y1_px:.2f} {x2_px:.2f} {y2_px:.2f}\n")

    print(f"Conversion complete! Output saved to {output_file}")

convert_yolo_to_coords(coord_path, SCRIPT_DIR / "coords_pixel.txt", SCRIPT_DIR / "sample_image.bmp")
