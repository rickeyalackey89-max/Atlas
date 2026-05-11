"""
King of Spades — Slip of the Day card generator.
Outputs: king_of_spades_20260508.png (720x1080)
Dark background with Matrix-style falling cyan formula streams.
"""
from PIL import Image, ImageDraw, ImageFont
import os, numpy as np, random

MKTG    = os.path.dirname(os.path.abspath(__file__))
OG_PATH = os.path.join(MKTG, "og_anunoby.png")
OUT_PATH= os.path.join(MKTG, "king_of_spades_20260508.png")

W, H = 720, 1080

# ── Colors ────────────────────────────────────────────────
CYAN          = (0,   210, 230)
CYAN_DARK     = (0,   160, 175)
CYAN_DIM      = (0,   100, 115)
CYAN_BRIGHT   = (120, 240, 255)
BG_BLACK      = (4,   10,  18)
PANEL_BG      = (8,   18,  28)
BLACK         = (4,   10,  18)
WHITE         = (255, 255, 255)
OFF_WHITE     = (220, 235, 240)
GOBLIN_GREEN  = (34,  197, 94)
STANDARD_BLUE = (80,  160, 255)
MID_GRAY      = (100, 120, 130)
LIGHT_GRAY    = (180, 200, 210)

# ── Slip data ─────────────────────────────────────────────
LEGS = [
    ("Devin Vassell",    "OVER  REB  2.5",  "GOBLIN"),
    ("OG Anunoby",       "OVER  FG3M 1.5",  "GOBLIN"),
    ("Terrence Shannon", "OVER  PTS  10",   "STANDARD"),
    ("Anthony Edwards",  "UNDER PA   26.5", "STANDARD"),
]
HIT_PROB = 0.5447
PAYOUT   = "10x"
EV_MULT  = 1.796
CONF     = 0.860
TIER_COLOR = {"GOBLIN": GOBLIN_GREEN, "STANDARD": STANDARD_BLUE}
ROW_FILL   = {"GOBLIN": (34, 197, 94, 45), "STANDARD": (80, 160, 255, 45)}


def get_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for suffix in ("bd", "b", "i", ""):
        p = f"C:/Windows/Fonts/{name}{suffix}.ttf"
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ═══════════════════════════════════════════════════════════
# LAYER 1 — Dark background with rounded corners
# ═══════════════════════════════════════════════════════════
card = Image.new("RGBA", (W, H), (*BG_BLACK, 255))
mask = Image.new("L", (W, H), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, W-1, H-1], radius=44, fill=255)
card.putalpha(mask)
draw = ImageDraw.Draw(card)

# ═══════════════════════════════════════════════════════════
# LAYER 2 — Matrix rain: falling columns of Atlas formula tokens
# ═══════════════════════════════════════════════════════════
RAIN_TOKENS = [
    "p_cal", "logit", "Brier", "AUC", "LODO", "sigma", "mu", "lambda",
    "0.199", "E[y]", "p^2", "Sigma", "Phi", "alpha", "beta", "integral", "Pi",
    "rate", "edge", "sim", "CV", "EV", "GBM", "p_adj", "p_role",
    "Kelly", "T=1.06", "10K", "0.545", "0.860", "OVER", "UNDER",
    "REB", "PTS", "FG3M", "PA", "min", "z", "n/k", "delta",
    "0.5", "1-p", "log", "exp", "ROC", "F1", "shrink",
    "q", "b*p", "GOBLIN", "DEMON", "share", "blowout", "p_blend",
    "189K", "38d", "IAEL", "LODO", "isotonic", "beam", "seed",
]

_rng = random.Random(7)
fnt_rain_sm = get_font("arial", 13)
fnt_rain_md = get_font("arialbd", 14)

rain_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))

# Wider column pitch — rotated tokens are taller so need more horizontal room
COL_PITCH = 16
for cx in range(8, W - 8, COL_PITCH):
    length  = _rng.randint(18, 44)
    start_y = _rng.randint(-80, 40)
    for j in range(length):
        tok  = _rng.choice(RAIN_TOKENS)
        fnt  = fnt_rain_md if _rng.random() < 0.2 else fnt_rain_sm
        frac = j / max(length - 1, 1)
        if j == 0:
            col = CYAN_BRIGHT; a = 240
        elif frac < 0.15:
            col = CYAN;        a = 200
        elif frac < 0.45:
            col = CYAN_DARK;   a = int(155 - frac * 120)
        else:
            col = CYAN_DIM;    a = int(90  - frac * 60)
        a = max(15, min(255, a))

        # Render token onto scratch, rotate 90° so it reads sideways as it falls
        _tmp_d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        _tb = _tmp_d.textbbox((0, 0), tok, font=fnt)
        tw, th = _tb[2] - _tb[0] + 4, _tb[3] - _tb[1] + 4
        _scratch = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        ImageDraw.Draw(_scratch).text((2, 2), tok, font=fnt, fill=(*col, a))
        _rot = _scratch.rotate(90, expand=True)   # 90° — reads sideways, falls down

        # Step size = rotated token height (original width) so tokens stack without overlap
        step = tw + 2
        ty = start_y + j * step
        px = cx - _rot.width // 2
        py = ty
        if -_rot.height <= py <= H:
            rain_layer.paste(_rot, (px, py), _rot)

card = Image.alpha_composite(card, rain_layer)
draw = ImageDraw.Draw(card)

# ── Cyan glowing particle dots ────────────────────────────
glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow_layer)
for _ in range(160):
    gx = _rng.randint(10, W - 10)
    gy = _rng.randint(10, H - 10)
    gr = _rng.randint(1, 3)
    ga = _rng.randint(50, 130)
    gd.ellipse([gx-gr, gy-gr, gx+gr, gy+gr], fill=(*CYAN, ga))
card = Image.alpha_composite(card, glow_layer)
draw = ImageDraw.Draw(card)

# ═══════════════════════════════════════════════════════════
# LAYER 3 — Cyan border
# ═══════════════════════════════════════════════════════════
draw.rounded_rectangle([0,  0,  W-1,  H-1],  radius=44, outline=CYAN, width=8)
draw.rounded_rectangle([12, 12, W-13, H-13], radius=35, outline=(*CYAN_DARK, 80), width=1)

# ═══════════════════════════════════════════════════════════
# Fonts
# ═══════════════════════════════════════════════════════════
fnt_K      = get_font("arialbd", 80)
fnt_spade  = (
    ImageFont.truetype("C:/Windows/Fonts/NotoSans-Bold.ttf", 56)
    if os.path.exists("C:/Windows/Fonts/NotoSans-Bold.ttf")
    else ImageFont.truetype("C:/Windows/Fonts/arialuni.ttf", 52)
    if os.path.exists("C:/Windows/Fonts/arialuni.ttf")
    else get_font("seguisym", 52)
)
fnt_header = get_font("arialbd", 20)
fnt_name   = get_font("arialbd", 26)
fnt_pick   = get_font("arial",   22)
fnt_badge  = get_font("arialbd", 15)
fnt_val    = get_font("arialbd", 30)
fnt_brand  = get_font("arial",   15)

# ═══════════════════════════════════════════════════════════
# LAYER 4 — Corner index tiles (K / spade)
# ═══════════════════════════════════════════════════════════
CORNER_W, CORNER_H = 85, 145
tl = Image.new("RGBA", (CORNER_W, CORNER_H), (0, 0, 0, 0))
tl_d = ImageDraw.Draw(tl)
tl_d.text((6, 0),   "K", font=fnt_K,     fill=CYAN)
tl_d.text((14, 78), "♠", font=fnt_spade, fill=CYAN)
_clip = Image.new("L", (CORNER_W, CORNER_H), 0)
ImageDraw.Draw(_clip).rectangle([0, 0, CORNER_W-1, CORNER_H-1], fill=255)
tl.putalpha(Image.fromarray(
    np.minimum(np.array(tl.getchannel("A")), np.array(_clip))
))
card.paste(tl, (16, 14), tl)

br_tile = Image.new("RGBA", (CORNER_W, CORNER_H), (0, 0, 0, 0))
br_d = ImageDraw.Draw(br_tile)
br_d.text((6, 0),   "K", font=fnt_K,     fill=CYAN)
br_d.text((14, 78), "♠", font=fnt_spade, fill=CYAN)
_br_clip = Image.new("L", (CORNER_W, CORNER_H), 0)
ImageDraw.Draw(_br_clip).rectangle([0, 0, CORNER_W-1, CORNER_H-1], fill=255)
br_tile.putalpha(Image.fromarray(
    np.minimum(np.array(br_tile.getchannel("A")), np.array(_br_clip))
))
br = br_tile.rotate(180)
card.paste(br, (W - CORNER_W - 16, H - CORNER_H - 14), br)
draw = ImageDraw.Draw(card)

# ═══════════════════════════════════════════════════════════
# LAYER 5 — OG Anunoby photo
# ═══════════════════════════════════════════════════════════
og = Image.open(OG_PATH).convert("RGBA")
og_target_h = 390
og_w = int(og.width * (og_target_h / og.height))
og = og.resize((og_w, og_target_h), Image.LANCZOS)
og_x = (W - og_w) // 2
og_y = 116  # midpoint between 35 and 197
card.paste(og, (og_x, og_y), og)
draw = ImageDraw.Draw(card)

# ═══════════════════════════════════════════════════════════
# LAYER 6 — Lower panel: dark semi-transparent overlay
# ═══════════════════════════════════════════════════════════
DIV_Y = og_y + og_target_h + 6
panel_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
ImageDraw.Draw(panel_overlay).rectangle([0, DIV_Y, W, H], fill=(*PANEL_BG, 215))
card = Image.alpha_composite(card, panel_overlay)
draw = ImageDraw.Draw(card)

draw.line([(50, DIV_Y), (W - 50, DIV_Y)], fill=CYAN, width=2)

# ── SLIP OF THE DAY header ─────────────────────────────────
HDR_Y = DIV_Y + 14
draw.text((W // 2, HDR_Y), "♠  SLIP OF THE DAY  ♠",
          font=fnt_header, fill=CYAN, anchor="mt")

# ── Date pill ─────────────────────────────────────────────
EV_BADGE_Y = HDR_Y + 34
from datetime import date as _date
ev_label = _date.today().strftime("%B %d, %Y").replace(" 0", " ")
fnt_ev = get_font("arialbd", 17)
_tmp_d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
bbox   = _tmp_d.textbbox((0, 0), ev_label, font=fnt_ev)
pill_w = (bbox[2] - bbox[0]) + 28
pill_h = 26
pill_x = (W - pill_w) // 2
draw.rounded_rectangle([pill_x, EV_BADGE_Y, pill_x + pill_w, EV_BADGE_Y + pill_h],
                        radius=13, fill=CYAN_DARK)
draw.text((W // 2, EV_BADGE_Y + pill_h // 2), ev_label,
          font=fnt_ev, fill=WHITE, anchor="mm")

# ═══════════════════════════════════════════════════════════
# LAYER 7 — 4 Leg rows
# ═══════════════════════════════════════════════════════════
LEG_Y = EV_BADGE_Y + pill_h + 10
ROW_H = 64
PAD_X = 36

for i, (player, pick, tier) in enumerate(LEGS):
    ry = LEG_Y + i * ROW_H
    tc = TIER_COLOR[tier]
    if i > 0:
        draw.line([(PAD_X, ry - 2), (W - PAD_X, ry - 2)], fill=(*CYAN_DIM, 80), width=1)
    row_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(row_overlay).rounded_rectangle(
        [PAD_X, ry + 2, W - PAD_X, ry + 56], radius=8, fill=ROW_FILL[tier]
    )
    card = Image.alpha_composite(card, row_overlay)
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle([PAD_X, ry + 4, PAD_X + 4, ry + 52], radius=2, fill=tc)
    draw.text((PAD_X + 14, ry + 4),  player.upper(), font=fnt_name, fill=OFF_WHITE)
    draw.text((PAD_X + 14, ry + 33), pick,            font=fnt_pick, fill=(*CYAN_DARK, 220))
    bw, bh = 90, 24
    bx = W - bw - PAD_X
    by = ry + 17
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=8, fill=(*tc, 35))
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=8, outline=tc, width=1)
    draw.text((bx + bw // 2, by + bh // 2), tier, font=fnt_badge, fill=tc, anchor="mm")

# ═══════════════════════════════════════════════════════════
# LAYER 8 — Stats bar
# ═══════════════════════════════════════════════════════════
STAT_Y = LEG_Y + 4 * ROW_H + 12
draw.line([(50, STAT_Y), (W - 50, STAT_Y)], fill=CYAN, width=2)
SV_Y = STAT_Y + 14

_cols = [
    ("WIN PROB", f"{HIT_PROB:.1%}",  GOBLIN_GREEN,  "lt", "lm"),
    ("PAYOUT",   PAYOUT,             CYAN,          "mt", "mm"),
    ("EV MULT",  f"{EV_MULT:.2f}x",  CYAN,          "mt", "mm"),
    ("CONF",     f"{CONF:.1%}",       STANDARD_BLUE, "rt", "rm"),
]
_col_xs  = [60, W//2 - 95, W//2 + 95, W - 60]
fnt_lbl2 = get_font("arialbd", 13)
_tmp_d2  = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

for (_lbl, _val, _col, _al, _av), _x in zip(_cols, _col_xs):
    _lb  = _tmp_d2.textbbox((0, 0), _lbl, font=fnt_lbl2)
    _lw, _lh = _lb[2] - _lb[0], _lb[3] - _lb[1]
    _pad = 7
    if _al == "lt":   _px = _x - _pad
    elif _al == "rt": _px = _x - _lw - _pad
    else:             _px = _x - _lw // 2 - _pad
    draw.rounded_rectangle(
        [_px, SV_Y - 1, _px + _lw + _pad * 2, SV_Y + _lh + 6],
        radius=6, fill=(*CYAN_DIM, 120)
    )
    draw.text((_x, SV_Y + 2),        _lbl, font=fnt_lbl2, fill=LIGHT_GRAY, anchor=_al)
    draw.text((_x, SV_Y + _lh + 20), _val, font=fnt_val,  fill=_col,       anchor=_av)

# ── Branding ───────────────────────────────────────────────
draw.text((W // 2, H - 24), "atlassports.ai  •  ATLAS PREMIUM",
          font=fnt_brand, fill=(*CYAN_DIM, 180), anchor="mm")

# ═══════════════════════════════════════════════════════════
# FINAL — clip to card shape
# ═══════════════════════════════════════════════════════════
_final_mask = Image.new("L", (W, H), 0)
ImageDraw.Draw(_final_mask).rounded_rectangle([0, 0, W-1, H-1], radius=44, fill=255)
final = Image.new("RGBA", (W, H), (0, 0, 0, 0))
final = Image.alpha_composite(final, card)
_alpha = np.minimum(np.array(final.getchannel("A")), np.array(_final_mask))
final.putalpha(Image.fromarray(_alpha))
final.save(OUT_PATH, "PNG")
print(f"[OK] Saved: {OUT_PATH}")