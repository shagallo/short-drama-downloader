"""生成应用图标：红果品牌红渐变圆角方块 + 白色播放键，多尺寸 ICO。"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parent
SRC = OUT_DIR / "static" / "assets" / "app_icon.ico"
LEGACY = OUT_DIR / "static" / "assets" / "app_icon_legacy.ico"
PNG_OUT = OUT_DIR / "static" / "assets" / "app_icon.png"

S = 1024  # 超采样画布


def rounded_rect_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def build_icon() -> Image.Image:
    img = Image.new("RGB", (S, S))
    top = (255, 107, 95)     # #ff6b5f
    bottom = (255, 51, 44)   # #ff332c
    px = img.load()
    for y in range(S):
        # 轻微对角渐变，更有层次
        for x in range(S):
            t = (x * 0.35 + y * 0.65) / S
            px[x, y] = lerp(top, bottom, t)

    draw = ImageDraw.Draw(img)

    # 高光：左上角柔和亮斑
    highlight = Image.new("L", (S, S), 0)
    hd = ImageDraw.Draw(highlight)
    hd.ellipse([-S * 0.25, -S * 0.35, S * 0.75, S * 0.45], fill=70)
    white = Image.new("RGB", (S, S), (255, 255, 255))
    img = Image.composite(white, img, highlight.point(lambda v: int(v * 0.35)))

    # 白色播放三角形（圆角视觉用多边形近似 + 圆形顶点）
    cx, cy = S * 0.54, S * 0.5
    w, h = S * 0.34, S * 0.40
    p1 = (cx - w / 2, cy - h / 2)
    p2 = (cx - w / 2, cy + h / 2)
    p3 = (cx + w / 2, cy)
    d2 = ImageDraw.Draw(img)
    d2.polygon([p1, p2, p3], fill=(255, 255, 255))
    r = S * 0.018
    for p in (p1, p2, p3):
        d2.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=(255, 255, 255))

    # 圆角裁剪
    mask = rounded_rect_mask(S, int(S * 0.22))
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main() -> None:
    if SRC.exists() and not LEGACY.exists():
        LEGACY.write_bytes(SRC.read_bytes())
        print(f"旧图标已备份: {LEGACY.name}")

    icon = build_icon()
    icon.save(PNG_OUT)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    icon.save(SRC, format="ICO", sizes=sizes)
    print(f"已生成: {SRC.name} sizes={sizes}")
    print(f"已生成: {PNG_OUT.name}")


if __name__ == "__main__":
    main()
