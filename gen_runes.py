"""Рунные пластины: 4 варианта глифов на тёмной подложке (светится только рисунок)."""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).parent / "textures"
OUT.mkdir(exist_ok=True)

BG = (0, 0, 0, 0)          # прозрачный фон: на камне светится только глиф
GLOW = (60, 170, 255, 255)
CORE = (150, 225, 255, 255)   # не белое ядро: иначе эмиссия выбивает руну в жёлтый


def glyph(seed):
    S = 128
    im = Image.new("RGBA", (S, S), BG)
    d = ImageDraw.Draw(im)
    rnd = random.Random(seed)
    pts = [(32, 20), (64, 20), (96, 20), (32, 64), (64, 64), (96, 64), (32, 108), (64, 108), (96, 108)]
    d.line([(64, 20), (64, 108)], fill=GLOW, width=10)                # ствол руны
    for _ in range(rnd.randint(3, 4)):
        a, b = rnd.sample(pts, 2)
        d.line([a, b], fill=GLOW, width=9)
    im = im.filter(ImageFilter.GaussianBlur(3))
    d = ImageDraw.Draw(im)
    d.line([(64, 16), (64, 112)], fill=CORE, width=4)
    rnd = random.Random(seed)
    for _ in range(rnd.randint(3, 4)):
        a, b = rnd.sample(pts, 2)
        d.line([a, b], fill=CORE, width=4)
    return im


for i in range(4):
    glyph(11 + i * 7).save(OUT / f"rune_{i}.png")
print("ok", sorted(p.name for p in OUT.iterdir()))
