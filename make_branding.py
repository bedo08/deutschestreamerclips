"""Branding fuer den Kanal "Deutschestreamerclips" (Boss, 2026-11-08).

- Profilbild 800x800: eigenes Logo (Monogramm DSC + Play-Ecke), bewusst OHNE
  das Gesicht eines Streamers: ein fremdes Gesicht als Profilbild wirkt wie
  der offizielle Kanal des Streamers (Sperr-Risiko wegen Identitaetsvortaeuschung).
- Banner 2560x1440: Spielbilder aus den Streams als abgedunkelter Hintergrund,
  Titel + Untertitel im sicheren Bereich (1546x423 Mitte), der auf jedem
  Geraet sichtbar ist.
- Schriften: Anton + Poppins Bold aus fonts/ (OFL), keine Windows-Systemschriften.

Hintergrundbilder: branding/frames/*.png (per ffmpeg aus einem Stream gezogen).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "branding"
FRAMES = OUT / "frames"
ANTON = str(HERE / "fonts" / "Anton-Regular.ttf")
POPPINS = str(HERE / "fonts" / "Poppins-Bold.ttf")

PURPLE = (145, 70, 255)      # Twitch-nah
ORANGE = (255, 122, 24)
DARK = (12, 9, 22)
WHITE = (255, 255, 255)


def text_center(draw, cx, y, text, font, fill, stroke=0, stroke_fill=(0, 0, 0)):
    b = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    draw.text((cx - (b[2] - b[0]) / 2 - b[0], y - b[1]), text, font=font, fill=fill,
              stroke_width=stroke, stroke_fill=stroke_fill)
    return b[3] - b[1]


def make_profile_picture():
    s = 800
    img = Image.new("RGB", (s, s), DARK)
    glow = Image.new("RGB", (s, s), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse([120, 120, 680, 680], fill=PURPLE)
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.blend(img, glow, 0.55)
    d = ImageDraw.Draw(img)
    d.ellipse([60, 60, 740, 740], outline=PURPLE, width=22)
    d.ellipse([95, 95, 705, 705], outline=ORANGE, width=8)
    font = ImageFont.truetype(ANTON, 300)
    text_center(d, s / 2, 215, "DSC", font, WHITE, stroke=6, stroke_fill=DARK)
    cx, cy = s / 2, 590
    d.polygon([(cx - 38, cy - 45), (cx - 38, cy + 45), (cx + 48, cy)], fill=ORANGE)
    img.save(OUT / "profile_picture.png")


def collage(w, h):
    frames = sorted(FRAMES.glob("*.png"))
    bg = Image.new("RGB", (w, h), DARK)
    if not frames:
        return bg
    n = len(frames)
    strip_w = w / n
    skew = 260
    for i, f in enumerate(frames):
        im = Image.open(f).convert("RGB")
        im = im.resize((int(h * im.width / im.height), h))
        cw = int(strip_w + skew)
        cut = im.crop(((im.width - cw) // 2, 0, (im.width + cw) // 2, h))
        mask = Image.new("L", cut.size, 0)
        ImageDraw.Draw(mask).polygon([(skew, 0), (cut.width, 0),
                                      (cut.width - skew, h), (0, h)], fill=255)
        bg.paste(cut, (int(i * strip_w) - skew // 2, 0), mask)
    bg = ImageEnhance.Brightness(bg).enhance(0.38)
    return ImageEnhance.Color(bg).enhance(1.2)


def make_banner():
    w, h = 2560, 1440
    img = collage(w, h)
    band = Image.new("L", (w, h), 0)
    ImageDraw.Draw(band).rectangle([0, h / 2 - 260, w, h / 2 + 260], fill=170)
    band = band.filter(ImageFilter.GaussianBlur(60))
    img = Image.composite(Image.new("RGB", (w, h), DARK), img, band)
    d = ImageDraw.Draw(img)
    title = ImageFont.truetype(ANTON, 148)  # Titel muss in den sicheren Bereich (1546 px breit)
    sub = ImageFont.truetype(POPPINS, 52)
    top = h / 2 - 160
    th = text_center(d, w / 2, top, "DEUTSCHE STREAMER CLIPS", title, WHITE, stroke=4)
    y = top + th + 34
    d.rectangle([w / 2 - 230, y, w / 2, y + 10], fill=PURPLE)
    d.rectangle([w / 2, y, w / 2 + 230, y + 10], fill=ORANGE)
    text_center(d, w / 2, y + 44, "Die besten Twitch-Momente. Jeden Tag neu.", sub,
                (230, 222, 245))
    img.save(OUT / "banner.png")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    make_profile_picture()
    make_banner()
    print("fertig:", OUT)
