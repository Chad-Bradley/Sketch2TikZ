"""
Setup script: extract easy/medium/hard zip files into data/{difficulty}/.

Usage:
    python scripts/setup_data.py          # extract all three
    python scripts/setup_data.py --level easy   # extract only easy
"""
import os
import sys
import zipfile
import shutil
import argparse
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

ZIP_CONFIG = {
    "easy": ROOT / "easy.zip",
    "medium": ROOT / "medium.zip",
    "hard": ROOT / "hard.zip",
}


def extract_one(level: str) -> bool:
    """Extract a single difficulty-level zip into data/{level}/."""
    zip_path = ZIP_CONFIG.get(level)
    if zip_path is None:
        print(f"[ERROR] Unknown level: {level}")
        return False
    if not zip_path.exists():
        print(f"[WARN] {zip_path.name} not found, skipping.")
        return False

    target = DATA_DIR / level
    target.mkdir(parents=True, exist_ok=True)

    print(f"[EXTRACT] {zip_path.name} -> {target}/")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmpdir)

        # Move files from nested subdirs into target flat
        for sub in tmpdir.iterdir():
            if sub.is_dir():
                for item in sub.iterdir():
                    dest = target / item.name
                    if dest.exists():
                        dest.unlink()
                    shutil.move(str(item), str(dest))
            elif sub.is_file():
                dest = target / sub.name
                if dest.exists():
                    dest.unlink()
                shutil.move(str(sub), str(dest))

    # Count what we got
    files = list(target.iterdir())
    pngs = [f for f in files if f.suffix == ".png"]
    parquets = [f for f in files if f.suffix == ".parquet"]
    print(f"  -> {len(parquets)} parquet(s), {len(pngs)} PNG(s), {len(files)} total files")
    return True


def main():
    parser = argparse.ArgumentParser(description="Extract difficulty-level datasets")
    parser.add_argument("--level", choices=["easy", "medium", "hard"],
                        help="Extract only one level (default: all three)")
    args = parser.parse_args()

    if args.level:
        levels = [args.level]
    else:
        levels = ["easy", "medium", "hard"]

    ok = 0
    for lv in levels:
        if extract_one(lv):
            ok += 1

    print(f"\n[DONE] {ok}/{len(levels)} datasets ready in {DATA_DIR}/")
    if ok == len(levels):
        print("All datasets loaded — you can now run: python evaluate.py --difficulty easy")


if __name__ == "__main__":
    main()
