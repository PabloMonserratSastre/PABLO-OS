"""Generate square PNG icon variants without changing the supplied fish artwork."""
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[2]
source = Image.open(root / "public/assets/pablo-logo-transparent.png").convert("RGBA")
for size in (180, 192, 512):
    icon = source.copy()
    icon.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (232, 241, 250, 255))
    canvas.alpha_composite(icon, ((size - icon.width) // 2, (size - icon.height) // 2))
    canvas.save(root / f"public/assets/pablo-app-{size}.png")
