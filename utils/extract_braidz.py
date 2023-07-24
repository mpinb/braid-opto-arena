import time
from pathlib import Path
from zipfile import ZipFile

from tqdm import tqdm

FOLDER = "/media/benyishay_la/Data/Experiments"

FILE = "20230714_151827.braidz"

FULLPATH = Path(FOLDER, FILE)

print(f"Extracting {FULLPATH}...")

with ZipFile(FULLPATH, "r") as zip_ref:
    for file in tqdm(iterable=zip_ref.namelist(), total=len(zip_ref.namelist())):
        zip_ref.extract(member=file, path=FULLPATH.with_suffix(""))
        time.sleep(0.1)
