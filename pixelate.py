"""Рендеры -> пиксель-арт: даунскейл, ограниченная палитра, тёмная обводка, лист стадий.

Запуск: python pixelate.py
    renders_hi/*.png  ->  sprites/*.png (прозрачный фон)  +  sheet.png
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).parent
HI, OUT = ROOT / "renders_hi", ROOT / "sprites"
OUT.mkdir(exist_ok=True)

SPRITE = 192          # сторона спрайта стадии, px
HERO = 384
COLORS = 32           # размер палитры
OUTLINE = (26, 20, 24, 255)
SHEET_BG = (92, 88, 74, 255)


RUNE_BLUES = [(30, 74, 122), (56, 132, 194), (104, 190, 240), (176, 232, 255)]
EMBERS = [(122, 32, 12), (214, 76, 20), (252, 148, 42), (255, 214, 130)]
FORCED = RUNE_BLUES + EMBERS


def shared_palette(sources, colors=COLORS):
    """Одна палитра на все спрайты: адаптивная по рендерам + принудительные синие для рун.

    Без этого руны занимают доли процента кадра, MEDIANCUT не выделяет им слот,
    и синее свечение съезжает в тёплый цвет.
    """
    tiles = []
    for src in sources:
        im = Image.open(src).convert("RGBA")
        bg = Image.new("RGBA", im.size, (0, 0, 0, 0))
        bg.alpha_composite(im)
        tiles.append(bg.convert("RGB").resize((128, 128), Image.BOX))
    strip = Image.new("RGB", (128 * len(tiles), 128))
    for i, t in enumerate(tiles):
        strip.paste(t, (i * 128, 0))
    adaptive = strip.quantize(colors=colors - len(FORCED), method=Image.MEDIANCUT).getpalette()
    flat = adaptive[: (colors - len(FORCED)) * 3]
    for c in FORCED:
        flat += list(c)
    pal = Image.new("P", (1, 1))
    pal.putpalette(flat + [0] * (768 - len(flat)))
    return pal


def quantize(im, pal):
    """Квантование только по видимым пикселям, альфа остаётся бинарной."""
    a = im.getchannel("A").point(lambda v: 255 if v > 110 else 0)
    q = im.convert("RGB").quantize(palette=pal, dither=Image.Dither.NONE).convert("RGB")
    q.putalpha(a)
    return q


def outline(im, color=OUTLINE):
    """1px тёмный контур по краю силуэта — как в пиксель-арте."""
    a = im.getchannel("A")
    w, h = im.size
    res = Image.new("RGBA", (w + 2, h + 2), (0, 0, 0, 0))
    ring = Image.new("RGBA", (w + 2, h + 2), (0, 0, 0, 0))
    solid = Image.new("RGBA", (w, h), color)
    for dx, dy in ((0, 1), (2, 1), (1, 0), (1, 2), (0, 0), (2, 0), (0, 2), (2, 2)):
        ring.paste(solid, (dx, dy), a)
    res.alpha_composite(ring)
    res.paste(im, (1, 1), a)
    return res


def pixelate(src, size, pal):
    im = Image.open(src).convert("RGBA")
    small = im.resize((size, size), Image.BOX)          # усреднение: чище, чем NEAREST
    return outline(quantize(small, pal))


def upscale(im, factor):
    return im.resize((im.width * factor, im.height * factor), Image.NEAREST)


def label(d, xy, text, size=16, fill=(235, 230, 215)):
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", size)
    except OSError:
        f = ImageFont.load_default()
    d.text(xy, text, font=f, fill=fill)


def build_sheet(tiles, hero, scale=3):
    """Лист как на референсе: сетка стадий слева, крупный кадр справа."""
    ts = tiles[0].width * scale
    hs = hero.width * scale
    pad, gap = 18, 10
    left_w = ts * 2 + gap
    W = pad * 3 + left_w + hs
    H = pad * 2 + max(ts * 2 + gap, hs)
    sheet = Image.new("RGBA", (W, H), SHEET_BG)
    d = ImageDraw.Draw(sheet)
    for i, t in enumerate(tiles):
        x = pad + (i % 2) * (ts + gap)
        y = pad + (i // 2) * (ts + gap)
        d.rectangle([x - 2, y - 2, x + ts + 1, y + ts + 1], outline=(38, 34, 30), width=2)
        sheet.alpha_composite(upscale(t, scale), (x, y))
        label(d, (x + 8, y + 6), f"LVL {i + 1}")
    x = pad * 2 + left_w
    y = pad
    d.rectangle([x - 2, y - 2, x + hs + 1, y + hs + 1], outline=(38, 34, 30), width=2)
    sheet.alpha_composite(upscale(hero, scale), (x, y))
    label(d, (x + hs - 78, y + 8), "LVL 4", 20)
    return sheet


SRC = [HI / f"tier{t}.png" for t in (1, 2, 3, 4)] + [HI / "hero.png"]
PAL = shared_palette([s for s in SRC if s.exists()])

tiles = []
for t in (1, 2, 3, 4):
    src = HI / f"tier{t}.png"
    if not src.exists():
        continue
    sp = pixelate(src, SPRITE, PAL)
    sp.save(OUT / f"oven_lvl{t}.png")
    upscale(sp, 4).save(OUT / f"oven_lvl{t}_x4.png")
    tiles.append(sp)

hero = pixelate(HI / "hero.png", HERO, PAL)
hero.save(OUT / "oven_hero.png")
upscale(hero, 2).save(OUT / "oven_hero_x2.png")

if len(tiles) == 4:
    build_sheet(tiles, hero, scale=3).convert("RGB").save(ROOT / "sheet.png")
print("ok", sorted(p.name for p in OUT.iterdir()))
