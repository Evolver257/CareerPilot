from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs" / "assets"
FRAME_PATHS = [
    (ASSET_DIR / "dashboard.png", "Dashboard: funnel, Agent Trace, Token Usage"),
    (ASSET_DIR / "agent-trace.png", "Agent Trace: auditable run and retry"),
    (ASSET_DIR / "browser-tasks.png", "Browser Task: safety-gated local execution"),
]
SIZE = (1280, 820)


def load_font(size: int):
    candidates = [
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def make_frame(path: Path, caption: str) -> Image.Image:
    source = Image.open(path).convert("RGB")
    canvas = Image.new("RGB", SIZE, "#f8fafc")
    fitted = ImageOps.contain(source, (SIZE[0] - 32, SIZE[1] - 74))
    canvas.paste(fitted, ((SIZE[0] - fitted.width) // 2, 12))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, SIZE[1] - 48, SIZE[0], SIZE[1]), fill="#111827")
    draw.text((24, SIZE[1] - 36), caption, fill="#f8fafc", font=load_font(22))
    return canvas


def main() -> None:
    missing = [path for path, _ in FRAME_PATHS if not path.exists()]
    if missing:
        raise SystemExit(f"Missing screenshot(s): {', '.join(map(str, missing))}")
    frames = [make_frame(path, caption) for path, caption in FRAME_PATHS]
    frames[0].save(
        ASSET_DIR / "demo.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[1800, 1800, 2200],
        loop=0,
        optimize=False,
    )


if __name__ == "__main__":
    main()
