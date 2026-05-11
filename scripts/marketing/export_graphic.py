"""
Export a marketing HTML graphic to a high-resolution PNG using headless Chrome.
Usage: python export_graphic.py [html_file]
Default: exports free_pick_20260507.html -> free_pick_20260507.png at 1080x1080
"""
import subprocess
import sys
import pathlib
import shutil

from PIL import Image

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\13142\AppData\Local\Google\Chrome\Application\chrome.exe",
]

SCRIPT_DIR = pathlib.Path(__file__).parent
WIDTH, HEIGHT = 1080, 1080
# Chrome headless clips ~80-100px from the bottom of the viewport;
# render taller then crop back to the exact card size.
RENDER_HEIGHT = 1200


def find_chrome():
    for p in CHROME_PATHS:
        if pathlib.Path(p).exists():
            return p
    found = shutil.which("chrome") or shutil.which("google-chrome")
    if found:
        return found
    raise FileNotFoundError("Chrome not found. Check CHROME_PATHS in this script.")


def export(html_path: pathlib.Path, out_path: pathlib.Path):
    chrome = find_chrome()
    file_url = html_path.resolve().as_uri()

    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--window-size={WIDTH},{RENDER_HEIGHT}",
        f"--screenshot={out_path.resolve()}",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        file_url,
    ]

    print(f"Rendering: {html_path.name}")
    print(f"Output:    {out_path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    if out_path.exists() and out_path.stat().st_size > 10_000:
        # Crop to exact card dimensions — removes Chrome's bottom overhang
        img = Image.open(out_path)
        cropped = img.crop((0, 0, WIDTH, HEIGHT))
        cropped.save(out_path, format="PNG", optimize=False)
        print(f"✓ Exported {out_path.stat().st_size // 1024}KB PNG ({WIDTH}×{HEIGHT})")
    else:
        print("Export may have failed. Chrome stderr:")
        print(result.stderr[-2000:] if result.stderr else "(no stderr)")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        html_path = pathlib.Path(sys.argv[1])
    else:
        html_path = SCRIPT_DIR / "free_pick_20260507.html"

    out_path = html_path.with_suffix(".png")
    export(html_path, out_path)
    print(f"\nOpen: {out_path}")
