"""Generate Windows-safe opaque icon.png / icon.ico from icon-src.png."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
build = ROOT / "desktop" / "build"
web = ROOT / "web" / "public"


def main() -> None:
    src = Image.open(build / "icon-src.png").convert("RGBA")
    flat = Image.new("RGB", src.size, (26, 26, 28))
    flat.paste(src, (0, 0), src)
    flat_rgba = flat.convert("RGBA")
    flat_rgba.save(build / "icon.png", "PNG")
    flat_rgba.save(
        build / "icon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    web.mkdir(parents=True, exist_ok=True)
    flat_rgba.resize((256, 256), Image.Resampling.LANCZOS).save(web / "app-icon.png", "PNG")
    flat_rgba.resize((64, 64), Image.Resampling.LANCZOS).save(web / "favicon.png", "PNG")
    print("ok", flat_rgba.size, (build / "icon.ico").stat().st_size)


if __name__ == "__main__":
    main()
