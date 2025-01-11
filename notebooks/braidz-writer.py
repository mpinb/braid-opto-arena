#!/usr/bin/env python3
import gzip
import zipfile
import zlib
import shutil
from pathlib import Path
import sys


def repair_gzip_file(input_path: Path) -> bool:
    """
    Attempt to repair a corrupted gzip file in place.
    Returns True if repair was successful.
    """
    try:
        # First try normal decompression
        with open(input_path, "rb") as f:
            data = gzip.decompress(f.read())
        print(f"  {input_path.name} is valid, no repair needed")
        return True
    except:
        print(f"  Attempting to repair {input_path.name}")
        try:
            # Read the corrupted file
            with open(input_path, "rb") as f:
                corrupted_data = f.read()

            # Skip the gzip header and try raw deflate
            deflate_data = corrupted_data[10:]
            decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
            raw_data = decompressor.decompress(deflate_data)

            # If we got here, decompression worked - recompress properly
            with gzip.open(input_path, "wb", compresslevel=6) as f:
                f.write(raw_data)

            print(f"  Successfully repaired {input_path.name}")
            return True

        except Exception as e:
            print(f"  Failed to repair {input_path.name}: {str(e)}")
            return False


def create_braidz(input_dir: Path, output_file: Path) -> bool:
    """
    Create a braidz file from a directory, repairing gzipped files if needed.
    Returns True if successful.
    """
    try:
        input_dir = input_dir.resolve()
        if not input_dir.is_dir():
            print(f"Error: {input_dir} is not a directory")
            return False

        print(f"\nStep 1: Checking and repairing .csv.gz files in {input_dir}")
        # Find and repair all .csv.gz files
        for gz_file in input_dir.rglob("*.csv.gz"):
            repair_gzip_file(gz_file)

        print(f"\nStep 2: Creating {output_file}")
        # Create the braidz file
        with open(output_file, "wb") as f:
            # Write the header
            header = (
                "BRAIDZ file. This is a standard ZIP file with a "
                "specific schema. You can view the contents of this "
                "file at https://braidz.strawlab.org/\n"
            ).encode("utf-8")
            f.write(header)

            # Create ZIP archive
            with zipfile.ZipFile(f, "a", compression=zipfile.ZIP_STORED) as zf:
                # First handle README.md if it exists
                readme_path = input_dir / "README.md"
                if readme_path.exists():
                    print("  Adding README.md first")
                    zf.write(readme_path, "README.md")

                # Then add all other files
                for file_path in input_dir.rglob("*"):
                    if file_path.is_file() and file_path.name != "README.md":
                        rel_path = file_path.relative_to(input_dir)
                        print(f"  Adding {rel_path}")
                        zf.write(file_path, rel_path)

        print(f"\nSuccessfully created {output_file}")
        return True

    except Exception as e:
        print(f"\nError creating braidz file: {str(e)}")
        return False


def main():
    """
    Main function to create a .braidz file from a given input directory.
    This function expects two command-line arguments: the input directory containing braid files
    and the output file path for the resulting .braidz file. If the output file already exists,
    a backup is created with a .braidz.bak extension.
    Usage:
        python script.py <input_braid_folder> <output_braidz_file>
    Returns:
        int: 0 if the .braidz file was created successfully, 1 otherwise.
    """
    if len(sys.argv) != 3:
        print("Usage: python script.py <input_braid_folder> <output_braidz_file>")
        return 1

    input_dir = Path(sys.argv[1])
    output_file = Path(sys.argv[2])

    # Create backup of output file if it exists
    if output_file.exists():
        backup = output_file.with_suffix(".braidz.bak")
        print(f"Creating backup of existing braidz file: {backup}")
        shutil.copy2(output_file, backup)

    success = create_braidz(input_dir, output_file)
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
