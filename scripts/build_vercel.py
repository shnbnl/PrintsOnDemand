"""Publish the existing /static URLs through Vercel's public directory."""

from pathlib import Path
import shutil


def main():
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "app" / "static", root / "public" / "static", dirs_exist_ok=True)
    print("Static assets prepared in public/static.")


if __name__ == "__main__":
    main()
