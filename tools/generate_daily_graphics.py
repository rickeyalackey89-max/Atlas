#!/usr/bin/env python3
"""
Daily Graphics Generator - Visual Content Creation
===============================================
Creates visual subscriber content from daily picks CSV.

Features:
- Tier-based graphics (GOBLIN, STANDARD, DEMON)
- Social media ready images
- Branded design templates
- Automated text layout

Usage:
    python -m tools.generate_daily_graphics --csv data/output/graphics/daily_picks.csv
"""

import argparse
import pandas as pd
import os
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import textwrap

# Design constants
CARD_WIDTH = 1080
CARD_HEIGHT = 1080
CARD_MARGIN = 60
HEADER_HEIGHT = 120
FOOTER_HEIGHT = 80

# Color schemes by tier - Enhanced with more POP
TIER_COLORS = {
    'GOBLIN': {
        'bg': '#FFFFFF',           # Clean white
        'bg_gradient': '#F5F5F5',  # Slight off-white gradient
        'accent': '#111111',      # Near-black
        'accent_glow': '#444444', # Dark gray glow
        'text': '#111111',        # Near-black
        'subtitle': '#666666',    # Medium gray
        'card_bg': '#F2F2F2',     # Light gray pick boxes
        'court_line': '#AAAAAA',  # Visible dark gray court lines
        'overlay_alpha': 0        # No dark overlay on white bg
    },
    'STANDARD': {
        'bg': '#FFFFFF',
        'bg_gradient': '#F5F5F5',
        'accent': '#111111',
        'accent_glow': '#444444',
        'text': '#111111',
        'subtitle': '#666666',
        'card_bg': '#F2F2F2',
        'court_line': '#AAAAAA',
        'overlay_alpha': 0
    },
    'DEMON': {
        'bg': '#FFFFFF',
        'bg_gradient': '#F5F5F5',
        'accent': '#111111',
        'accent_glow': '#444444',
        'text': '#111111',
        'subtitle': '#666666',
        'card_bg': '#F2F2F2',
        'court_line': '#AAAAAA',
        'overlay_alpha': 0
    }
}

# Tier messaging - Enhanced
TIER_MESSAGING = {
    'GOBLIN': {
        'title': 'LOCK PICKS',
        'subtitle': 'CHAMPIONSHIP CONFIDENCE',
        'emoji': '🔒',
        'tagline': 'MONEY IN THE BANK'
    },
    'STANDARD': {
        'title': 'SOLID PLAYS',
        'subtitle': 'PLAYOFF WORTHY BETS',
        'emoji': '💎',
        'tagline': 'CONSISTENT WINNERS'
    },
    'DEMON': {
        'title': 'MOON SHOTS',
        'subtitle': 'ALL-STAR SPECULATION',
        'emoji': '🚀',
        'tagline': 'HIGH RISK - BIG REWARDS'
    }
}

# Stat name (PrizePicks) -> gamelog column(s)
STAT_TO_COLS = {
    'PTS':  ['pts'],
    'REB':  ['reb'],
    'AST':  ['ast'],
    'FG3M': ['fg3m'],
    'PRA':  ['pts', 'reb', 'ast'],
    'PA':   ['pts', 'ast'],
    'PR':   ['pts', 'reb'],
    'RA':   ['reb', 'ast'],
    'FTA':  ['fta'],
    'TOV':  ['tov'],
}

_GL_CACHE: dict = {}


def _ascii_name(s: str) -> str:
    """Normalize accented characters to ASCII for fuzzy player matching."""
    import unicodedata
    return unicodedata.normalize('NFD', s).encode('ascii', 'ignore').decode('ascii').lower().strip()


def get_player_last5(player_name: str, stat: str, gamelogs_path) -> list:
    """Return last 5 game values (oldest -> newest) for player + stat."""
    global _GL_CACHE
    if 'df' not in _GL_CACHE:
        try:
            import pandas as _pd
            _GL_CACHE['df'] = _pd.read_csv(str(gamelogs_path), on_bad_lines='skip')
        except Exception:
            _GL_CACHE['df'] = None
    gl = _GL_CACHE.get('df')
    if gl is None:
        return []
    cols = STAT_TO_COLS.get(stat.upper(), [])
    if not cols:
        return []
    _pname = _ascii_name(player_name)
    mask = gl['player'].apply(_ascii_name) == _pname
    pgl  = gl[mask].copy()
    import pandas as _pd2
    pgl['_gd'] = _pd2.to_datetime(pgl['game_date'], format='mixed', errors='coerce')
    pgl  = pgl.sort_values('_gd', ascending=False).head(5).iloc[::-1]
    values = []
    for _, row in pgl.iterrows():
        try:
            values.append(sum(float(row[c]) for c in cols if c in row.index))
        except Exception:
            pass
    return values


def draw_direction_arrow(draw, cx, cy, direction, size=18, color='#111111'):
    """Draw a filled triangle pointing up (OVER) or down (UNDER)."""
    if direction.upper() == 'OVER':
        pts = [(cx, cy - size), (cx - size, cy + size//2), (cx + size, cy + size//2)]
    else:
        pts = [(cx, cy + size), (cx - size, cy - size//2), (cx + size, cy - size//2)]
    draw.polygon(pts, fill=color)


def get_font(size, bold=False):
    """Get system font with fallbacks."""
    try:
        # Try to use system fonts
        font_paths = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf", 
            "/System/Library/Fonts/Arial.ttf",  # macOS
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"  # Linux
        ]
        
        if bold:
            font_paths.insert(0, "C:/Windows/Fonts/arialbd.ttf")
            font_paths.insert(1, "C:/Windows/Fonts/calibrib.ttf")
        
        for font_path in font_paths:
            if os.path.exists(font_path):
                return ImageFont.truetype(font_path, size)
        
        # Fallback to default
        return ImageFont.load_default()
    except:
        return ImageFont.load_default()

def draw_atlas_logo(draw, x, y, size=100, color_scheme='light'):
    """Draw the ATLAS logo with globe and dollar sign."""
    # Colors
    if color_scheme == 'light':
        globe_color = '#2563EB'      # Blue
        dollar_color = '#10B981'     # Green
        text_color = '#1F2937'       # Dark gray
        border_color = '#374151'     # Medium gray
    else:  # dark scheme
        globe_color = '#60A5FA'      # Light blue
        dollar_color = '#34D399'     # Light green  
        text_color = '#F9FAFB'       # Light gray
        border_color = '#9CA3AF'     # Light gray
    
    # Globe circle
    globe_radius = size // 3
    globe_center_x = x
    globe_center_y = y + size // 4
    
    # Draw globe outer circle
    globe_box = [
        globe_center_x - globe_radius,
        globe_center_y - globe_radius,
        globe_center_x + globe_radius,
        globe_center_y + globe_radius
    ]
    draw.ellipse(globe_box, fill=globe_color, outline=border_color, width=3)
    
    # Draw continents (simple shapes)
    continent_color = '#1E40AF' if color_scheme == 'light' else '#3B82F6'
    
    # North America (rough shape)
    na_points = [
        (globe_center_x - globe_radius//2, globe_center_y - globe_radius//3),
        (globe_center_x - globe_radius//4, globe_center_y - globe_radius//2),
        (globe_center_x + globe_radius//4, globe_center_y - globe_radius//4),
        (globe_center_x + globe_radius//3, globe_center_y),
        (globe_center_x - globe_radius//3, globe_center_y + globe_radius//4),
        (globe_center_x - globe_radius//2, globe_center_y)
    ]
    draw.polygon(na_points, fill=continent_color)
    
    # Dollar sign in center of globe
    dollar_font = get_font(globe_radius // 2, bold=True)
    draw.text((globe_center_x, globe_center_y), '$', 
             font=dollar_font, fill=dollar_color, anchor="mm")
    
    # ATLAS text below globe
    atlas_font = get_font(size // 4, bold=True)
    text_y = globe_center_y + globe_radius + 15
    draw.text((x, text_y), 'A T L A S', 
             font=atlas_font, fill=text_color, anchor="mm")

def draw_nba_court_background(img, colors):
    """Draw NBA basketball court background pattern."""
    draw = ImageDraw.Draw(img)

    # Solid background fill
    draw.rectangle([0, 0, CARD_WIDTH, CARD_HEIGHT], fill=colors['bg'])

    line_color = colors['court_line']
    lw = 3   # standard court line width

    center_x, center_y = CARD_WIDTH // 2, CARD_HEIGHT // 2

    # ── HALF-COURT LINE ──────────────────────────────────────────────────────
    draw.line([0, center_y, CARD_WIDTH, center_y], fill=line_color, width=lw)

    # ── TIP-OFF / CENTER CIRCLE ───────────────────────────────────────────────
    tip_r = 130
    draw.ellipse(
        [center_x - tip_r, center_y - tip_r, center_x + tip_r, center_y + tip_r],
        outline=line_color, width=lw
    )
    # Inner tip circle (small)
    inner_r = 18
    draw.ellipse(
        [center_x - inner_r, center_y - inner_r, center_x + inner_r, center_y + inner_r],
        outline=line_color, width=lw
    )

    # ── FREE-THROW LANES ─────────────────────────────────────────────────────
    lane_w = 160
    lane_h = 190
    lx = center_x - lane_w // 2
    rx = center_x + lane_w // 2

    # Top lane
    draw.rectangle([lx, 0, rx, lane_h], outline=line_color, width=lw)
    # Top free-throw circle
    ft_r = 72
    draw.arc([lx - (ft_r - lane_w // 2), lane_h - ft_r,
              rx + (ft_r - lane_w // 2), lane_h + ft_r],
             start=0, end=180, fill=line_color, width=lw)

    # Bottom lane
    draw.rectangle([lx, CARD_HEIGHT - lane_h, rx, CARD_HEIGHT], outline=line_color, width=lw)
    # Bottom free-throw circle
    draw.arc([lx - (ft_r - lane_w // 2), CARD_HEIGHT - lane_h - ft_r,
              rx + (ft_r - lane_w // 2), CARD_HEIGHT - lane_h + ft_r],
             start=180, end=360, fill=line_color, width=lw)

    # ── THREE-POINT ARCS ─────────────────────────────────────────────────────
    arc_r = 210

    # Top arc
    draw.arc([center_x - arc_r, 0 - arc_r, center_x + arc_r, 0 + arc_r],
             start=0, end=180, fill=line_color, width=lw)

    # Bottom arc
    draw.arc([center_x - arc_r, CARD_HEIGHT - arc_r,
              center_x + arc_r, CARD_HEIGHT + arc_r],
             start=180, end=360, fill=line_color, width=lw)

    # ── SIDELINE / BASELINE BORDER ────────────────────────────────────────────
    border = 30
    draw.rectangle([border, border, CARD_WIDTH - border, CARD_HEIGHT - border],
                   outline=line_color, width=lw)

def draw_text_with_glow(draw, pos, text, font, text_color, glow_color, glow_size=3):
    """Draw text with a glow effect for better visibility."""
    x, y = pos
    
    # Draw glow (multiple offset shadows)
    for offset in range(1, glow_size + 1):
        for dx in [-offset, 0, offset]:
            for dy in [-offset, 0, offset]:
                if dx != 0 or dy != 0:  # Skip center
                    draw.text((x + dx, y + dy), text, font=font, fill=glow_color, anchor="mm")
    
    # Draw main text
    draw.text(pos, text, font=font, fill=text_color, anchor="mm")

def create_tier_card(picks_df, tier, output_dir):
    """Create a graphics card for a specific tier with NBA court background."""

    tier_picks = picks_df[picks_df['tier'] == tier].head(10)
    if tier_picks.empty:
        return None

    colors   = TIER_COLORS[tier]
    messaging = TIER_MESSAGING[tier]

    # ── CANVAS ──────────────────────────────────────────────────────────────
    img = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), colors['bg'])
    draw_nba_court_background(img, colors)

    overlay_alpha = colors.get('overlay_alpha', 110)
    if overlay_alpha > 0:
        overlay      = Image.new('RGBA', (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle([0, 0, CARD_WIDTH, CARD_HEIGHT], fill=(0, 0, 0, overlay_alpha))
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    draw = ImageDraw.Draw(img)

    # ── FONTS ────────────────────────────────────────────────────────────────
    title_font  = get_font(62, bold=True)
    sub_font    = get_font(26, bold=True)
    date_font   = get_font(20)
    player_font = get_font(34, bold=True)
    stat_font   = get_font(23)
    rank_font   = get_font(38, bold=True)
    prob_font   = get_font(40, bold=True)
    footer_font = get_font(21)

    MARGIN = 50

    # ── BASKETBALL ICON ──────────────────────────────────────────────────────
    icon_img = None
    ICON_TARGET_H = 110   # desired height; width scales to preserve aspect ratio
    icon_path = Path(__file__).parent.parent / 'data' / 'output' / 'graphics' / 'Screenshot_20260502_095152_X (1).jpg'
    is_light_bg = colors.get('bg', '#000000').upper() in ('#FFFFFF', '#F5F5F5', '#F8F8F8', '#EEEEEE')
    if icon_path.exists():
        try:
            raw = Image.open(str(icon_path)).convert('RGBA')
            # Preserve aspect ratio — scale so height == ICON_TARGET_H
            orig_w, orig_h = raw.size
            scale = ICON_TARGET_H / orig_h
            ICON_W = max(1, int(orig_w * scale))
            ICON_H = ICON_TARGET_H
            raw = raw.resize((ICON_W, ICON_H), Image.LANCZOS)
            new_data = []
            for px in raw.getdata():
                if px[0] > 200 and px[1] > 200 and px[2] > 200:
                    new_data.append((0, 0, 0, 0))          # transparent bg (white -> clear)
                elif is_light_bg:
                    new_data.append((17, 17, 17, 255))     # dark silhouette on white bg
                else:
                    new_data.append((255, 255, 255, 255))  # white silhouette on dark bg
            raw.putdata(new_data)
            icon_img = raw
        except Exception:
            icon_img = None
            ICON_W, ICON_H = 0, ICON_TARGET_H
    else:
        ICON_W, ICON_H = 0, ICON_TARGET_H

    # ── HEADER ───────────────────────────────────────────────────────────────
    header_top = 42

    # Strip emoji from title for clean PIL rendering
    import re as _re
    title_text = _re.sub(r'[^\x00-\x7F]+', '', messaging['title']).strip()

    # Measure title width to center [icon + title] as a unit
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_w    = title_bbox[2] - title_bbox[0]
    title_h    = title_bbox[3] - title_bbox[1]

    icon_gap = 20
    block_w  = (ICON_W + icon_gap + title_w) if icon_img else title_w
    block_x  = (CARD_WIDTH - block_w) // 2

    # Paste basketball icon
    icon_y = header_top + 4
    if icon_img:
        img.paste(icon_img, (block_x, icon_y), icon_img)
        title_x = block_x + ICON_W + icon_gap
    else:
        title_x = block_x

    # Title, vertically centered relative to icon height
    title_y = header_top + max(0, (ICON_H - title_h) // 2)
    draw.text((title_x, title_y), title_text,
              font=title_font, fill=colors['text'], anchor='lt')

    # Subtitle
    sub_y = header_top + ICON_H + 14
    draw.text((CARD_WIDTH // 2, sub_y), messaging['subtitle'],
              font=sub_font, fill=colors['text'], anchor='mt')

    # Date
    today  = datetime.now().strftime('%B %d, %Y').upper()
    date_y = sub_y + 36
    draw.text((CARD_WIDTH // 2, date_y), today,
              font=date_font, fill=colors['text'], anchor='mt')

    # Separator line
    sep_y = date_y + 26
    draw.line([MARGIN, sep_y, CARD_WIDTH - MARGIN, sep_y],
              fill=colors['accent'], width=2)

    # ── PICKS ────────────────────────────────────────────────────────────────
    PICK_H      = 104
    PICK_GAP    = 8
    picks_start = sep_y + 16

    # Parse accent color to RGBA for overlay drawing
    _ac = colors['accent'].lstrip('#')
    accent_rgba = (int(_ac[0:2],16), int(_ac[2:4],16), int(_ac[4:6],16))

    # Draw semi-transparent box backgrounds on a separate RGBA layer
    # so the court lines show through slightly
    box_overlay = Image.new('RGBA', (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    box_draw    = ImageDraw.Draw(box_overlay)
    for _bi in range(min(5, len(tier_picks))):
        _by = picks_start + _bi * (PICK_H + PICK_GAP)
        box_draw.rounded_rectangle(
            [MARGIN, _by, CARD_WIDTH - MARGIN, _by + PICK_H],
            radius=12,
            fill=(248, 248, 248, 185),                  # ~73% opaque — court shows through
            outline=(*accent_rgba, 230), width=2
        )
    img  = Image.alpha_composite(img.convert('RGBA'), box_overlay).convert('RGB')
    draw = ImageDraw.Draw(img)

    gamelogs_path = Path(__file__).parent.parent / 'data' / 'gamelogs' / 'nba_gamelogs.csv'

    for i, (_, pick) in enumerate(tier_picks.head(5).iterrows()):
        y = picks_start + i * (PICK_H + PICK_GAP)

        # Rank — left column, vertically centered
        draw.text((MARGIN + 44, y + PICK_H // 2),
                  f"#{int(pick['rank'])}",
                  font=rank_font, fill=colors['accent'], anchor='mm')

        # Vertical divider
        draw.line([MARGIN + 80, y + 14, MARGIN + 80, y + PICK_H - 14],
                  fill=colors['accent'], width=1)

        # Player name (truncated to leave room for bars)
        player_text = str(pick['player'])
        if len(player_text) > 16:
            player_text = player_text[:14] + '..'
        draw.text((MARGIN + 94, y + 18), player_text,
                  font=player_font, fill=colors['text'], anchor='lt')

        # Stat / direction / line (bottom-left)
        stat_text = f"{pick['stat']}  {pick['direction']}  {pick['line']}"
        draw.text((MARGIN + 94, y + PICK_H - 18), stat_text,
                  font=stat_font, fill=colors['subtitle'], anchor='lb')

        # ── MINI BAR CHART ───────────────────────────────────────────────────────────────
        # Blue palette: solid blue = hit, faded blue = miss
        BAR_HIT_COLOR  = '#4A90D9'   # medium sky blue
        BAR_MISS_COLOR = '#B8D4F0'   # pale / faded blue
        BAR_ARROW_COLOR = '#4A90D9'  # arrow matches hit bars

        BAR_X1     = MARGIN + 415    # shifted left
        BAR_X2     = CARD_WIDTH - MARGIN - 255  # condensed right edge, more room for arrow+prob
        BAR_Y1     = y + 22
        BAR_Y2     = y + PICK_H - 20
        bar_area_w = BAR_X2 - BAR_X1
        bar_area_h = BAR_Y2 - BAR_Y1

        last5 = get_player_last5(str(pick['player']), str(pick['stat']), gamelogs_path)
        if last5:
            try:
                line_val = float(pick['line'])
                max_val  = max(max(last5), line_val) * 1.25 or 1.0
                n        = len(last5)
                gap      = 4
                bar_w    = max(6, (bar_area_w - (n - 1) * gap) // n)
                total_w  = n * bar_w + (n - 1) * gap
                bx_start = BAR_X1 + (bar_area_w - total_w) // 2

                _is_over = str(pick['direction']).upper() == 'OVER'
                ref_y = BAR_Y2 - int((line_val / max_val) * bar_area_h)

                for bi, val in enumerate(last5):
                    bx   = bx_start + bi * (bar_w + gap)
                    bh   = max(3, int((val / max_val) * bar_area_h))
                    by_t = BAR_Y2 - bh
                    _hit = (val >= line_val) if _is_over else (val <= line_val)
                    bar_fill = BAR_HIT_COLOR if _hit else BAR_MISS_COLOR
                    draw.rounded_rectangle([bx, by_t, bx + bar_w, BAR_Y2],
                                           radius=2, fill=bar_fill)
                    if bh > 14:
                        draw.text((bx + bar_w // 2, by_t - 2),
                                  f"{val:.0f}", font=get_font(13),
                                  fill='#4A4A4A', anchor='mb')

                # Dashed reference line
                for _dx in range(0, total_w, 8):
                    seg_x1 = bx_start + _dx
                    seg_x2 = min(seg_x1 + 4, bx_start + total_w)
                    draw.line([seg_x1, ref_y, seg_x2, ref_y],
                              fill='#444444', width=2)
            except Exception:
                pass

        # ── DIRECTION ARROW ───────────────────────────────────────────────────────────────
        arrow_cx = CARD_WIDTH - MARGIN - 195
        arrow_cy = y + PICK_H // 2
        draw_direction_arrow(draw, arrow_cx, arrow_cy,
                             str(pick['direction']), size=14, color=BAR_ARROW_COLOR)

        # Probability — right column, vertically centered
        draw.text((CARD_WIDTH - MARGIN - 24, y + PICK_H // 2),
                  f"{pick['hit_probability_pct']}%",
                  font=prob_font, fill=colors['accent'], anchor='rm')

    # ── FOOTER ───────────────────────────────────────────────────────────────
    footer_y = picks_start + 5 * (PICK_H + PICK_GAP) - PICK_GAP + 18
    draw.line([MARGIN, footer_y, CARD_WIDTH - MARGIN, footer_y],
              fill=colors['accent'], width=2)

    # Tagline text
    draw.text((CARD_WIDTH // 2, footer_y + 18), messaging['tagline'],
              font=footer_font, fill=colors['subtitle'], anchor='mt')

    # ── ATLAS LOGO (8387.jpg) centered in footer ──────────────────────────
    LOGO_SIZE = 260
    logo_path = Path(__file__).parent.parent / 'data' / 'output' / 'graphics' / '8387.jpg'
    if logo_path.exists():
        try:
            logo_raw = Image.open(str(logo_path)).convert('RGBA')
            # Crop to square around the artwork (image is roughly square)
            w, h = logo_raw.size
            crop = min(w, h)
            cx, cy = w // 2, h // 2
            logo_raw = logo_raw.crop((cx - crop//2, cy - crop//2, cx + crop//2, cy + crop//2))
            logo_raw = logo_raw.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
            # Remove white/near-white background -> transparent; keep dark pixels
            logo_data = []
            for px in logo_raw.getdata():
                if px[0] > 220 and px[1] > 220 and px[2] > 220:
                    logo_data.append((0, 0, 0, 0))          # transparent
                elif is_light_bg:
                    logo_data.append((17, 17, 17, px[3]))   # near-black on white
                else:
                    logo_data.append((255, 255, 255, px[3])) # white on dark
            logo_raw.putdata(logo_data)
            logo_x = (CARD_WIDTH - LOGO_SIZE) // 2
            logo_y = footer_y + 48
            img.paste(logo_raw, (logo_x, logo_y), logo_raw)
            # Website below logo
            draw.text((CARD_WIDTH // 2, logo_y + LOGO_SIZE + 10),
                      'AtlasSports.AI',
                      font=get_font(20), fill=colors['subtitle'], anchor='mt')
        except Exception:
            # Fallback to text footer
            draw.text((CARD_WIDTH // 2, footer_y + 56),
                      'Powered by ATLAS  |  AtlasSports.AI',
                      font=get_font(19), fill=colors['subtitle'], anchor='mt')
    else:
        draw.text((CARD_WIDTH // 2, footer_y + 56),
                  'Powered by ATLAS  |  AtlasSports.AI',
                  font=get_font(19), fill=colors['subtitle'], anchor='mt')

    # Save
    output_path = output_dir / f'daily_{tier.lower()}_picks.png'
    img.save(str(output_path), 'PNG', quality=95)
    return output_path

def create_summary_card(picks_df, output_dir):
    """Create a summary card with all tiers and NBA court theming."""
    import re as _re

    colors = TIER_COLORS['GOBLIN']  # white/black scheme

    img = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), colors['bg'])
    draw_nba_court_background(img, colors)
    draw = ImageDraw.Draw(img)

    MARGIN = 50

    # ── HEADER ───────────────────────────────────────────────────────────────
    # Title
    title_font = get_font(72, bold=True)
    draw.text((CARD_WIDTH // 2, 52), 'DAILY NBA PICKS',
              font=title_font, fill=colors['text'], anchor='mt')

    # Large readable date
    date_font = get_font(38, bold=True)
    today = datetime.now().strftime('%A, %B %d, %Y').upper()
    draw.text((CARD_WIDTH // 2, 140), today,
              font=date_font, fill=colors['text'], anchor='mt')

    # Separator
    draw.line([MARGIN, 196, CARD_WIDTH - MARGIN, 196],
              fill=colors['accent'], width=3)

    # ── TIER SECTIONS (no boxes — plain text rows) ────────────────────────
    section_y = 216
    tier_title_font = get_font(26, bold=True)
    pick_name_font  = get_font(26, bold=True)
    pick_meta_font  = get_font(20)
    prob_font       = get_font(26, bold=True)

    for tier in ['GOBLIN', 'STANDARD', 'DEMON']:
        tier_picks = picks_df[picks_df['tier'] == tier]
        if tier_picks.empty:
            continue

        count    = len(tier_picks)
        avg_prob = tier_picks['hit_probability_pct'].mean()
        label    = TIER_MESSAGING[tier]['title']

        # Tier heading line
        draw.text((MARGIN, section_y), label,
                  font=tier_title_font, fill=colors['text'], anchor='lt')
        draw.text((CARD_WIDTH - MARGIN, section_y),
                  f"{count} picks  •  {avg_prob:.1f}% avg",
                  font=get_font(20), fill=colors['subtitle'], anchor='rt')

        section_y += 36

        # Top 3 picks per tier as clean text rows
        for _, pick in tier_picks.head(3).iterrows():
            player_text = str(pick['player'])
            if len(player_text) > 22:
                player_text = player_text[:20] + '..'
            stat_text = f"{pick['stat']}  {pick['direction']}  {pick['line']}"

            draw.text((MARGIN + 14, section_y), f"#{int(pick['rank'])}",
                      font=pick_meta_font, fill=colors['subtitle'], anchor='lt')
            draw.text((MARGIN + 54, section_y), player_text,
                      font=pick_name_font, fill=colors['text'], anchor='lt')
            draw.text((MARGIN + 54, section_y + 28), stat_text,
                      font=pick_meta_font, fill=colors['subtitle'], anchor='lt')
            draw.text((CARD_WIDTH - MARGIN, section_y + 14),
                      f"{pick['hit_probability_pct']}%",
                      font=prob_font, fill=colors['accent'], anchor='rm')

            section_y += 58

        # Thin divider between tiers
        draw.line([MARGIN, section_y + 2, CARD_WIDTH - MARGIN, section_y + 2],
                  fill=colors['court_line'], width=1)
        section_y += 14

    # ── FOOTER — ATLAS LOGO ───────────────────────────────────────────────
    footer_sep_y = CARD_HEIGHT - 230
    draw.line([MARGIN, footer_sep_y, CARD_WIDTH - MARGIN, footer_sep_y],
              fill=colors['accent'], width=2)

    LOGO_SIZE = 190
    logo_path = Path(__file__).parent.parent / 'data' / 'output' / 'graphics' / '8387.jpg'
    is_light_bg = True
    if logo_path.exists():
        try:
            logo_raw = Image.open(str(logo_path)).convert('RGBA')
            w, h = logo_raw.size
            crop = min(w, h)
            cx, cy = w // 2, h // 2
            logo_raw = logo_raw.crop((cx - crop//2, cy - crop//2, cx + crop//2, cy + crop//2))
            logo_raw = logo_raw.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
            logo_data = []
            for px in logo_raw.getdata():
                if px[0] > 220 and px[1] > 220 and px[2] > 220:
                    logo_data.append((0, 0, 0, 0))
                else:
                    logo_data.append((17, 17, 17, px[3]))
            logo_raw.putdata(logo_data)
            logo_x = (CARD_WIDTH - LOGO_SIZE) // 2
            logo_y = CARD_HEIGHT - 220
            img.paste(logo_raw, (logo_x, logo_y), logo_raw)
            draw = ImageDraw.Draw(img)
            draw.text((CARD_WIDTH // 2, CARD_HEIGHT - 18),
                      'AtlasSports.AI',
                      font=get_font(22), fill=colors['subtitle'], anchor='mb')
        except Exception:
            draw = ImageDraw.Draw(img)
            draw.text((CARD_WIDTH // 2, CARD_HEIGHT - 40),
                      'AtlasSports.AI',
                      font=get_font(22), fill=colors['subtitle'], anchor='mb')

    output_path = output_dir / 'daily_summary.png'
    img.save(str(output_path), 'PNG', quality=95)
    return output_path
def generate_pick_synopsis(player, stat, direction, line, team, opp, gamelogs_path, p_cal=None, leg_row=None):
    """Return a rich human-readable basketball reason for this pick.
    
    leg_row: optional dict with the full scored-leg row (from marketed_slips.json).
    When present, adds opponent defense, market consensus, role expansion, and game context.
    """
    global _GL_CACHE
    if 'df' not in _GL_CACHE:
        try:
            import pandas as _pd
            _GL_CACHE['df'] = _pd.read_csv(str(gamelogs_path), on_bad_lines='skip')
        except Exception:
            _GL_CACHE['df'] = None
    gl = _GL_CACHE.get('df')
    if gl is None:
        return None

    cols = STAT_TO_COLS.get(stat.upper(), [])
    if not cols:
        return None

    import pandas as _pd2
    _pname = _ascii_name(player)
    mask = gl['player'].apply(_ascii_name) == _pname
    pgl  = gl[mask].copy()
    if pgl.empty:
        return None

    pgl['_gd'] = _pd2.to_datetime(pgl['game_date'], format='mixed', errors='coerce')
    pgl = pgl.sort_values('_gd', ascending=False)

    try:
        line_val   = float(line)
        stat_label = stat.upper()
        is_over    = direction.upper() == 'OVER'

        # ── Last 5 stat values ──────────────────────────────────────────────
        recent5 = pgl.head(5).copy().iloc[::-1]   # oldest → newest
        last5_vals = []
        for _, row in recent5.iterrows():
            try:
                last5_vals.append(sum(float(row[c]) for c in cols if c in row.index))
            except Exception:
                pass
        if len(last5_vals) < 2:
            return None
        n   = len(last5_vals)
        avg = sum(last5_vals) / n
        hits = sum(1 for v in last5_vals if (v >= line_val if is_over else v <= line_val))

        # ── Trend: last 2 vs first 3 ────────────────────────────────────────
        early_avg = sum(last5_vals[:-2]) / max(1, len(last5_vals[:-2]))
        late_avg  = sum(last5_vals[-2:]) / 2
        trending  = 'up' if late_avg > early_avg * 1.10 else ('down' if late_avg < early_avg * 0.90 else 'flat')

        # ── Minutes context ─────────────────────────────────────────────────
        avg_min = None
        if 'minutes' in pgl.columns:
            try:
                avg_min = float(pgl.head(5)['minutes'].mean())
            except Exception:
                pass

        # ── Usage context ───────────────────────────────────────────────────
        usg = None
        if 'usg_proxy' in pgl.columns:
            try:
                usg = float(pgl.head(5)['usg_proxy'].mean())
            except Exception:
                pass

        # ── vs this opponent — pull ALL games for series count ──────────────
        opp_mask = pgl['opp'].str.upper().str.strip() == str(opp).upper().strip()
        opp_all  = pgl[opp_mask].copy()   # sorted newest first already

        # Limit to last 21 days — a full 7-game series cannot span more than 21 days
        cutoff = pgl['_gd'].max() - _pd2.Timedelta(days=21)
        opp_series = opp_all[opp_all['_gd'] >= cutoff]
        series_games_played = len(opp_series)
        game_number = min(series_games_played + 1, 7)   # today is the next game; max 7 in a series

        # Series label
        if game_number == 7:
            series_label = "GAME 7 — WINNER TAKE ALL"
        elif game_number == 6:
            series_label = "Game 6 — series on the line"
        elif game_number >= 4:
            series_label = f"Game {game_number} of series"
        else:
            series_label = None

        opp_rows = opp_series.head(3).copy().iloc[::-1]   # last 3, oldest→newest
        opp_vals = []
        for _, row in opp_rows.iterrows():
            try:
                opp_vals.append(sum(float(row[c]) for c in cols if c in row.index))
            except Exception:
                pass
        opp_hits = sum(1 for v in opp_vals if (v >= line_val if is_over else v <= line_val))
        opp_avg  = sum(opp_vals) / len(opp_vals) if opp_vals else None

        # ── Confidence label from p_cal ─────────────────────────────────────
        conf_str = ''
        if p_cal is not None:
            pct = int(round(float(p_cal) * 100))
            if pct >= 80:
                conf_str = f'Atlas: {pct}% confident — '
            elif pct >= 65:
                conf_str = f'Atlas likes this at {pct}% — '

        # ── Extra context from the full scored-leg row ───────────────────────
        lr = leg_row or {}
        def _lrf(key, default=None):
            v = lr.get(key)
            try:
                return float(v) if v is not None and str(v) != 'nan' else default
            except Exception:
                return default
        def _lrs(key, default=''):
            v = lr.get(key)
            return str(v) if v is not None else default

        # Opponent defense (negative = tougher, positive = softer)
        opp_def_rel   = _lrf('form_opp_defense_rel')          # e.g. -0.08 = 8% harder
        # Market consensus via OddsAPI
        ext_prior     = _lrf('external_prior_score')           # model's prior nudge probability
        ext_sources   = _lrs('external_prior_sources')
        # Home/away
        is_home       = bool(int(lr.get('home', 0) or 0))
        # 20-game edge over line (positive = player beating line)
        l20_edge      = _lrf('l20_edge', 0.0)
        # Role expansion (share matrix)
        role_reason   = _lrs('role_ctx_reason')
        role_outs     = int(_lrf('role_ctx_outs_used', 0) or 0)
        role_mult     = _lrf('role_ctx_mult', 1.0)
        role_comps    = _lrs('role_ctx_components')
        # Blowout probability
        q_blowout     = _lrf('q_blowout', 0.0)
        # Spread/game context
        spread_val    = _lrf('spread')

        # ── Build the sentence ───────────────────────────────────────────────
        min_str = f"{avg_min:.0f} min/g" if avg_min else ''
        usg_str = ''
        if usg is not None:
            if usg >= 0.30:
                usg_str = 'high-usage role'
            elif usg <= 0.15:
                usg_str = 'limited usage'

        last_name = player.split()[-1]

        # ── Resolve role-expansion out-player name ───────────────────────────
        import re as _re2
        out_name = None
        if role_outs > 0 and role_mult >= 1.04 and role_comps:
            m = _re2.search(r'out=([^,\)]+)', role_comps)
            if m:
                out_name = m.group(1).strip().title()

        # ── Minutes-collapse detection for UNDER ─────────────────────────────
        recent3_min = None
        earlier2_min = None
        if not is_over and 'minutes' in pgl.columns:
            try:
                recent3_min  = float(pgl.head(3)['minutes'].mean())
                earlier2_min = float(pgl.iloc[3:5]['minutes'].mean()) if len(pgl) >= 5 else None
            except Exception:
                pass
        min_collapsed = (
            recent3_min is not None and recent3_min < 18 and
            earlier2_min is not None and recent3_min < earlier2_min * 0.70
        )

        # ── Compose primary sentence ─────────────────────────────────────────
        primary = ''
        support = ''

        if is_over:
            diff = avg - line_val

            # Story 1: Series dominance — player is consistently clearing this line vs this opponent
            if opp_avg is not None and len(opp_vals) >= 2 and opp_hits >= len(opp_vals) - 1:
                if series_label:
                    primary = (
                        f"{series_label} — {last_name} is averaging {opp_avg:.1f} {stat_label} "
                        f"against {opp} this series, clearing {line_val:.0f} in {opp_hits} of {len(opp_vals)} games"
                    )
                else:
                    primary = (
                        f"{last_name} has gone {opp_hits} for {len(opp_vals)} on this line vs {opp}, "
                        f"averaging {opp_avg:.1f} {stat_label} in that stretch"
                    )

            # Story 2: Role expansion — teammate out creates real opportunity
            elif out_name:
                primary = (
                    f"With {out_name} out, {last_name} has stepped into an expanded role — "
                    f"his usage is up {int((role_mult-1)*100)}% and averaging {avg:.1f} {stat_label} this stretch"
                )

            # Story 3: Soft defense — matchup sets up the over
            elif opp_def_rel is not None and opp_def_rel > 0.06:
                def_pct = int(opp_def_rel * 100)
                primary = (
                    f"{opp} is allowing {def_pct}% more {stat_label} than the league average, "
                    f"and {last_name} is averaging {avg:.1f} against that soft defense"
                )

            # Story 4: Trending hot — recent form is the story
            elif trending == 'up':
                primary = (
                    f"{last_name} is on a hot streak — {late_avg:.1f} {stat_label} per game over "
                    f"his last two with the {line_val:.0f} line set before the run started"
                )

            # Story 5: Simply averaging over the line
            elif diff >= 1.5:
                primary = (
                    f"{last_name} is averaging {avg:.1f} {stat_label} over his last {n} games — "
                    f"the {line_val:.0f} line is set a step below what he's actually been doing"
                )

            # Story 6: Default — hitting it reliably
            else:
                primary = (
                    f"{last_name} has cleared {line_val:.0f} {stat_label} in {hits} of his last {n} games, "
                    f"averaging {avg:.1f} in that span"
                )

            # Supporting clause — pick the single strongest one
            if out_name and opp_avg is not None and len(opp_vals) >= 2:
                # Already had series story; add role angle
                support = (
                    f"with {out_name} out, his role is up {int((role_mult-1)*100)}% — "
                    f"more minutes, more shots, more production"
                )
            elif opp_avg is not None and opp_hits >= len(opp_vals) - 1 and opp_def_rel is not None and opp_def_rel > 0.06:
                def_pct = int(opp_def_rel * 100)
                support = f"{opp}'s defense is {def_pct}% below average — the matchup makes the history repeatable"
            elif opp_avg is not None and opp_hits >= len(opp_vals) - 1 and trending == 'up':
                support = f"trending even hotter lately — {late_avg:.1f} avg his last two"
            elif ext_prior is not None and 'oddsapi' in ext_sources.lower() and ext_prior >= 0.68:
                mkt_pct = int(ext_prior * 100)
                support = f"sharp market is aligned here at {mkt_pct}% — book and model agree"
            elif out_name and not opp_avg:
                # Role was the primary, add a soft-defense or trend kicker if available
                if opp_def_rel is not None and opp_def_rel > 0.04:
                    def_pct = int(opp_def_rel * 100)
                    support = f"{opp} is also {def_pct}% below average defensively — a soft spot to exploit"
                elif trending == 'up':
                    support = f"he's getting hotter with {late_avg:.1f} over his last two"
            elif trending == 'up' and diff >= 1.0 and not support:
                support = f"his form is accelerating — {late_avg:.1f} avg last two, still climbing"
            elif avg_min and avg_min >= 28 and not support:
                support = f"logging {avg_min:.0f} minutes a night — the floor time to produce is guaranteed"

        else:  # UNDER
            diff = line_val - avg

            # Story 1: Minutes collapse — the most compelling under story
            if min_collapsed:
                over_rate = sum(1 for v in last5_vals if v > line_val)
                if game_number == 7:
                    primary = (
                        f"{last_name}'s floor time has fallen to {recent3_min:.0f} minutes a game — "
                        f"in Game 7, coaches tighten rotations and bench minutes disappear entirely"
                    )
                elif game_number == 6:
                    primary = (
                        f"His minutes dropped from {earlier2_min:.0f} to {recent3_min:.0f} a game "
                        f"as the series has intensified — crunch-time rosters shrink and he's on the outside"
                    )
                else:
                    primary = (
                        f"{last_name}'s floor time has dropped from {earlier2_min:.0f} to {recent3_min:.0f} "
                        f"minutes a game — without consistent run, reaching {line_val:.0f} {stat_label} is a stretch"
                    )
                # Support: even before the collapse, he wasn't clearing it consistently
                if over_rate <= 2:
                    support = (
                        f"even when healthy and getting more run, he only cleared {line_val:.0f} "
                        f"{stat_label} {over_rate} of his last {n} games"
                    )

            # Story 2: Series UNDER pattern — this specific matchup has been brutal
            elif opp_avg is not None and len(opp_vals) >= 2 and opp_hits >= len(opp_vals) - 1:
                primary = (
                    f"{last_name} has averaged just {opp_avg:.1f} {stat_label} against {opp} "
                    f"this series, staying under {line_val:.0f} in {opp_hits} of {len(opp_vals)} matchups"
                )
                if opp_def_rel is not None and opp_def_rel < -0.06:
                    def_pct = int(abs(opp_def_rel) * 100)
                    support = (
                        f"{opp} is playing {def_pct}% better defense than league average — "
                        f"the matchup history is no coincidence"
                    )
                elif trending == 'down':
                    support = f"his production has been fading too — only {late_avg:.1f} over his last two"

            # Story 3: Strong defense — the wall the player has to climb
            elif opp_def_rel is not None and opp_def_rel < -0.08:
                def_pct = int(abs(opp_def_rel) * 100)
                primary = (
                    f"{opp} is playing {def_pct}% better defense than the league average right now — "
                    f"reaching {line_val:.0f} {stat_label} against this unit is a legitimate ask"
                )
                if diff >= 1.0:
                    support = (
                        f"{last_name} is averaging just {avg:.1f} {stat_label} recently — "
                        f"already trending below the line before the tough matchup"
                    )

            # Story 4: Production simply below the line
            elif diff >= 1.5:
                primary = (
                    f"{last_name} is averaging just {avg:.1f} {stat_label} over his last {n} games — "
                    f"the books have set the {line_val:.0f} line above what he's actually been producing"
                )
                if trending == 'down':
                    support = f"and the trend is moving the wrong way — only {late_avg:.1f} over his last two"
                elif avg_min and avg_min < 22:
                    support = f"he's also only getting {avg_min:.0f} minutes a night, which caps the ceiling"

            # Story 5: Fading production trend
            elif trending == 'down':
                primary = (
                    f"{last_name}'s {stat_label} production has been trending down — "
                    f"averaging just {late_avg:.1f} over his last two games against a {line_val:.0f} line"
                )
                if avg_min and avg_min < 20:
                    support = f"his minutes are also dipping to {avg_min:.0f}/game, reducing touches"

            # Story 6: Default — hitting it regularly
            else:
                primary = (
                    f"{last_name} has stayed under {line_val:.0f} {stat_label} in {hits} of his last "
                    f"{n} games, averaging {avg:.1f} against a line that's set too high"
                )

            # Market consensus as additional kicker if support is empty
            if not support and ext_prior is not None and 'oddsapi' in ext_sources.lower() and ext_prior <= 0.38:
                mkt_pct = int((1 - ext_prior) * 100)
                support = (
                    f"the market is pricing the under at {mkt_pct}% implied — "
                    f"sharp books and the model are pointing the same direction"
                )

        # ── Assemble final sentence (primary + optional support) ─────────────
        sentence = primary if primary else f"Atlas model projects value on {stat_label} {direction}"
        if support:
            sentence = sentence.rstrip('.') + ' — ' + support[0].lower() + support[1:]

        # Prepend confidence if it fits and adds something
        if conf_str and len(conf_str + sentence) < 100:
            sentence = conf_str + sentence[0].lower() + sentence[1:]

        # Hard cap: ~3 visual lines at ~42 chars/line = 126 chars. Trim at last — boundary.
        if len(sentence) > 120:
            # Prefer trimming at a ' — ' boundary so we end on a complete thought
            cutpoint = sentence.rfind(' — ', 0, 120)
            if cutpoint > 40:
                sentence = sentence[:cutpoint] + '.'
            else:
                sentence = sentence[:120].rsplit(' ', 1)[0].rstrip('.,;— ') + '.'

        return sentence

    except Exception:
        return None


def create_slip_card(slip_df, leg_count, output_dir, leg_context=None):
    """Create a marketed slip card for a given leg count (3, 4, or 5)."""
    import re as _re
    colors    = TIER_COLORS['GOBLIN']   # white/black for all slips
    is_light_bg = True
    gamelogs_path = Path(__file__).parent.parent / 'data' / 'gamelogs' / 'nba_gamelogs.csv'

    img = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), colors['bg'])
    draw_nba_court_background(img, colors)
    draw = ImageDraw.Draw(img)

    MARGIN = 50

    # ── BASKETBALL ICON ──────────────────────────────────────────────────────
    ICON_TARGET_H = 90
    ICON_W = 0
    icon_img = None
    icon_path = Path(__file__).parent.parent / 'data' / 'output' / 'graphics' / 'Screenshot_20260502_095152_X (1).jpg'
    if icon_path.exists():
        try:
            raw = Image.open(str(icon_path)).convert('RGBA')
            orig_w, orig_h = raw.size
            ICON_W = max(1, int(orig_w * (ICON_TARGET_H / orig_h)))
            raw = raw.resize((ICON_W, ICON_TARGET_H), Image.LANCZOS)
            nd = []
            for px in raw.getdata():
                if px[0] > 200 and px[1] > 200 and px[2] > 200:
                    nd.append((0, 0, 0, 0))
                else:
                    nd.append((17, 17, 17, 255))
            raw.putdata(nd)
            icon_img = raw
        except Exception:
            pass

    # ── HEADER ───────────────────────────────────────────────────────────────
    header_top  = 36
    title_font  = get_font(64, bold=True)
    title_text  = f"{leg_count}-LEG PARLAY"

    title_bbox  = draw.textbbox((0, 0), title_text, font=title_font)
    title_w     = title_bbox[2] - title_bbox[0]
    title_h     = title_bbox[3] - title_bbox[1]
    icon_gap    = 18
    block_w     = (ICON_W + icon_gap + title_w) if icon_img else title_w
    block_x     = (CARD_WIDTH - block_w) // 2

    if icon_img:
        img.paste(icon_img, (block_x, header_top), icon_img)
        title_x = block_x + ICON_W + icon_gap
    else:
        title_x = block_x

    draw.text((title_x, header_top + max(0, (ICON_TARGET_H - title_h) // 2)),
              title_text, font=title_font, fill=colors['text'], anchor='lt')

    # Slip stats: win prob | payout | ev
    hit_prob = slip_df['hit_prob'].iloc[0]
    payout   = slip_df['payout_mult'].iloc[0]
    ev       = slip_df['ev'].iloc[0]

    stats_y    = header_top + ICON_TARGET_H + 12
    stats_font = get_font(28, bold=True)
    stats_sub  = get_font(18)
    col_xs     = [CARD_WIDTH // 4, CARD_WIDTH // 2, 3 * CARD_WIDTH // 4]
    for cx, lbl, val in zip(col_xs,
                             ['WIN PROBABILITY', 'PAYOUT', 'EXPECTED VALUE'],
                             [f"{hit_prob * 100:.1f}%", f"{payout:.2f}x", f"{ev:.2f}"]):
        draw.text((cx, stats_y),      val, font=stats_font, fill=colors['accent'], anchor='mt')
        draw.text((cx, stats_y + 34), lbl, font=stats_sub,  fill=colors['subtitle'], anchor='mt')

    date_y = stats_y + 64
    draw.text((CARD_WIDTH // 2, date_y),
              datetime.now().strftime('%B %d, %Y').upper(),
              font=get_font(18), fill=colors['subtitle'], anchor='mt')

    sep_y = date_y + 26
    draw.line([MARGIN, sep_y, CARD_WIDTH - MARGIN, sep_y], fill=colors['accent'], width=2)

    # ── LEG ROWS ─────────────────────────────────────────────────────────────
    FOOTER_RESERVE = 240
    legs_start = sep_y + 16
    n = len(slip_df)
    available_h = CARD_HEIGHT - legs_start - FOOTER_RESERVE
    LEG_H   = max(128, min(170, available_h // n - 6))
    LEG_GAP = 6

    # Batch semi-transparent box + badge overlays in one pass
    _ac        = colors['accent'].lstrip('#')
    accent_rgba = (int(_ac[0:2], 16), int(_ac[2:4], 16), int(_ac[4:6], 16))

    TIER_BADGE_BG = {'GOBLIN': (17,17,17), 'STANDARD': (85,85,85), 'DEMON': (160,160,160)}
    TIER_BADGE_FG = {'GOBLIN': '#FFFFFF',  'STANDARD': '#FFFFFF',  'DEMON': '#111111'}

    layer = Image.new('RGBA', (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    ld    = ImageDraw.Draw(layer)
    for li, (_, leg) in enumerate(slip_df.iterrows()):
        by = legs_start + li * (LEG_H + LEG_GAP)
        # Box
        ld.rounded_rectangle([MARGIN, by, CARD_WIDTH - MARGIN, by + LEG_H],
                              radius=12, fill=(248, 248, 248, 185),
                              outline=(*accent_rgba, 230), width=2)
        # Tier badge
        tier_key  = str(leg['tier']).upper()
        badge_bg  = TIER_BADGE_BG.get(tier_key, (85, 85, 85))
        bx1 = CARD_WIDTH - MARGIN - 210
        bx2 = bx1 + 72
        by1 = by + 12
        by2 = by1 + 26
        ld.rounded_rectangle([bx1, by1, bx2, by2], radius=6, fill=(*badge_bg, 230))
    img  = Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')
    draw = ImageDraw.Draw(img)

    player_font  = get_font(30, bold=True)
    meta_font    = get_font(19)
    prob_font    = get_font(30, bold=True)
    rank_font    = get_font(30, bold=True)
    syn_font     = get_font(15)   # synopsis line

    BAR_HIT_COLOR   = '#4A90D9'
    BAR_MISS_COLOR  = '#B8D4F0'
    BAR_ARROW_COLOR = '#4A90D9'

    for li, (_, leg) in enumerate(slip_df.iterrows()):
        y     = legs_start + li * (LEG_H + LEG_GAP)
        mid_y = y + LEG_H // 2

        # Synopsis (computed once per leg)
        _lc = leg_context or {}
        _lkey = (_ascii_name(str(leg['player'])),
                 str(leg['stat']).upper(),
                 str(leg['direction']).upper())
        synopsis = generate_pick_synopsis(
            str(leg['player']), str(leg['stat']), str(leg['direction']),
            leg['line'], str(leg['team']), str(leg['opp']), gamelogs_path,
            p_cal=leg.get('p_cal'),
            leg_row=_lc.get(_lkey),
        ) if LEG_H >= 110 else None

        # Leg number
        draw.text((MARGIN + 40, mid_y), str(li + 1),
                  font=rank_font, fill=colors['accent'], anchor='mm')
        draw.line([MARGIN + 68, y + 12, MARGIN + 68, y + LEG_H - 12],
                  fill=colors['accent'], width=1)

        # Player name + stat line (+ optional synopsis)
        player_text = str(leg['player'])
        if len(player_text) > 17:
            player_text = player_text[:15] + '..'
        draw.text((MARGIN + 82, y + 12), player_text,
                  font=player_font, fill=colors['text'], anchor='lt')
        # Synopsis — word-wrapped to fit left column (before bar chart starts)
        if synopsis:
            SYN_MAX_X   = MARGIN + 380   # stay left of bar area
            SYN_TEXT_X  = MARGIN + 82
            SYN_MAX_W   = SYN_MAX_X - SYN_TEXT_X
            LINE_H      = 17
            SYN_START_Y = y + 46

            # Greedy word-wrap using textbbox
            words = synopsis.split()
            lines = []
            current = ''
            for word in words:
                test = (current + ' ' + word).strip()
                w = draw.textbbox((0, 0), test, font=syn_font)[2]
                if w <= SYN_MAX_W:
                    current = test
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)

            for li2, line_txt in enumerate(lines[:3]):   # max 3 lines
                draw.text((SYN_TEXT_X, SYN_START_Y + li2 * LINE_H),
                          line_txt, font=syn_font, fill='#666666', anchor='lt')
        matchup = f"{leg['team']} vs {leg['opp']}"
        draw.text((MARGIN + 82, y + LEG_H - 12),
                  f"{leg['stat']}  {leg['direction']}  {leg['line']}  •  {matchup}",
                  font=meta_font, fill=colors['subtitle'], anchor='lb')

        # ── BAR CHART ────────────────────────────────────────────────────────
        BAR_X1 = MARGIN + 390
        BAR_X2 = CARD_WIDTH - MARGIN - 230
        BAR_Y1 = y + 14
        BAR_Y2 = y + LEG_H - 12
        bar_area_w = BAR_X2 - BAR_X1
        bar_area_h = BAR_Y2 - BAR_Y1

        last5 = get_player_last5(str(leg['player']), str(leg['stat']), gamelogs_path)
        if last5:
            try:
                line_val = float(leg['line'])
                max_val  = max(max(last5), line_val) * 1.25 or 1.0
                ng = len(last5); gap = 4
                bar_w = max(6, (bar_area_w - (ng - 1) * gap) // ng)
                total_w = ng * bar_w + (ng - 1) * gap
                bx_start = BAR_X1 + (bar_area_w - total_w) // 2
                _is_over2 = str(leg['direction']).upper() == 'OVER'
                ref_y2 = BAR_Y2 - int((line_val / max_val) * bar_area_h)

                for bi, val in enumerate(last5):
                    bx    = bx_start + bi * (bar_w + gap)
                    bh    = max(3, int((val / max_val) * bar_area_h))
                    byt   = BAR_Y2 - bh
                    _hit2 = (val >= line_val) if _is_over2 else (val <= line_val)
                    draw.rounded_rectangle([bx, byt, bx + bar_w, BAR_Y2],
                                           radius=2,
                                           fill=BAR_HIT_COLOR if _hit2 else BAR_MISS_COLOR)
                    if bh > 12:
                        draw.text((bx + bar_w // 2, byt - 2), f"{val:.0f}",
                                  font=get_font(11), fill='#4A4A4A', anchor='mb')
                for _dx in range(0, total_w, 8):
                    sx1 = bx_start + _dx
                    draw.line([sx1, ref_y2, min(sx1 + 4, bx_start + total_w), ref_y2],
                              fill='#444444', width=2)
            except Exception:
                pass

        # Tier badge text (drawn after box compositing)
        tier_key = str(leg['tier']).upper()
        badge_fg = TIER_BADGE_FG.get(tier_key, '#FFFFFF')
        bx1 = CARD_WIDTH - MARGIN - 210
        bx2 = bx1 + 72
        by1 = y + 12
        by2 = by1 + 26
        draw.text(((bx1 + bx2) // 2, (by1 + by2) // 2),
                  tier_key[:3], font=get_font(14, bold=True), fill=badge_fg, anchor='mm')

        # Direction arrow + probability
        draw_direction_arrow(draw, CARD_WIDTH - MARGIN - 110, mid_y,
                             str(leg['direction']), size=12, color=BAR_ARROW_COLOR)
        p_pct = int(round(float(leg['p_cal']) * 100))
        draw.text((CARD_WIDTH - MARGIN - 22, mid_y),
                  f"{p_pct}%", font=prob_font, fill=colors['accent'], anchor='rm')

    # ── FOOTER ───────────────────────────────────────────────────────────────
    footer_y = legs_start + n * (LEG_H + LEG_GAP) - LEG_GAP + 14
    draw.line([MARGIN, footer_y, CARD_WIDTH - MARGIN, footer_y],
              fill=colors['accent'], width=2)

    # Logo size scales down automatically if 5-leg pushes footer low
    logo_y     = footer_y + 10
    LOGO_SIZE  = min(220, max(110, CARD_HEIGHT - logo_y - 46))   # 46 = atlaspicks.com + padding
    logo_path = Path(__file__).parent.parent / 'data' / 'output' / 'graphics' / '8387.jpg'
    if logo_path.exists():
        try:
            logo_raw = Image.open(str(logo_path)).convert('RGBA')
            w, h = logo_raw.size
            crop = min(w, h)
            cx2, cy2 = w // 2, h // 2
            logo_raw = logo_raw.crop((cx2 - crop//2, cy2 - crop//2, cx2 + crop//2, cy2 + crop//2))
            logo_raw = logo_raw.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
            ld2 = []
            for px in logo_raw.getdata():
                if px[0] > 220 and px[1] > 220 and px[2] > 220:
                    ld2.append((0, 0, 0, 0))
                else:
                    ld2.append((17, 17, 17, px[3]))
            logo_raw.putdata(ld2)
            logo_x = (CARD_WIDTH - LOGO_SIZE) // 2
            logo_y = footer_y + 10
            img.paste(logo_raw, (logo_x, logo_y), logo_raw)
            draw = ImageDraw.Draw(img)
            draw.text((CARD_WIDTH // 2, logo_y + LOGO_SIZE + 8),
                      'AtlasSports.AI', font=get_font(20), fill=colors['subtitle'], anchor='mt')
        except Exception:
            draw = ImageDraw.Draw(img)
            draw.text((CARD_WIDTH // 2, footer_y + 30),
                      'Powered by ATLAS  |  AtlasSports.AI',
                      font=get_font(19), fill=colors['subtitle'], anchor='mt')
    else:
        draw.text((CARD_WIDTH // 2, footer_y + 30),
                  'Powered by ATLAS  |  AtlasSports.AI',
                  font=get_font(19), fill=colors['subtitle'], anchor='mt')

    output_path = output_dir / f'slip_{leg_count}leg.png'
    img.save(str(output_path), 'PNG', quality=95)
    return output_path


def generate_slip_graphics(marketed_slips_path, output_dir):
    """Generate 3-leg, 4-leg, and 5-leg slip cards from marketed_slips.csv."""
    df = pd.read_csv(marketed_slips_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load the full leg context from marketed_slips.json if it exists alongside the CSV
    # Keyed by (ascii_player, stat, direction) -> leg dict
    leg_context: dict = {}
    ms_json = Path(marketed_slips_path).with_suffix('.json')
    if not ms_json.exists():
        # Try same basename in run dir
        ms_json = Path(marketed_slips_path).parent / 'marketed_slips.json'
    if ms_json.exists():
        try:
            import json as _json
            raw = _json.loads(ms_json.read_text(encoding='utf-8'))
            slips_list = raw.get('slips', raw) if isinstance(raw, dict) else raw
            for slip in slips_list:
                for leg in slip.get('legs', []):
                    key = (_ascii_name(str(leg.get('player', ''))),
                           str(leg.get('stat', '')).upper(),
                           str(leg.get('direction', '')).upper())
                    leg_context[key] = leg
        except Exception:
            pass

    generated = []
    for leg_label in ['3-leg', '4-leg', '5-leg']:
        slip = df[df['slip'] == leg_label]
        if slip.empty:
            print(f"  No {leg_label} data — skipping")
            continue
        leg_count = int(leg_label.split('-')[0])
        print(f"Creating {leg_label} slip card ({len(slip)} legs)...")
        path = create_slip_card(slip, leg_count, output_dir, leg_context=leg_context)
        if path:
            generated.append(path)
            print(f"   📸 {path}")
    return generated


def generate_graphics(csv_path, output_dir):
    """Generate all daily graphics from CSV."""
    
    # Load picks data
    df = pd.read_csv(csv_path)
    
    # Validate required columns
    required_cols = ['tier', 'player', 'stat', 'direction', 'line', 'hit_probability_pct', 'rank']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")
    
    # Create output directory
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    generated_files = []
    
    print(f"🎨 Generating graphics from {len(df)} picks...")
    
    # Generate tier cards
    for tier in ['GOBLIN', 'STANDARD', 'DEMON']:
        tier_picks = df[df['tier'] == tier]
        if not tier_picks.empty:
            print(f"Creating {tier} card ({len(tier_picks)} picks)...")
            output_path = create_tier_card(df, tier, output_dir)
            if output_path:
                generated_files.append(output_path)
    
    # Generate summary card
    print("Creating summary card...")
    summary_path = create_summary_card(df, output_dir)
    generated_files.append(summary_path)
    
    return generated_files

def main():
    parser = argparse.ArgumentParser(description="Generate daily graphics from picks CSV")
    parser.add_argument("--csv", required=False, default=None, help="Path to daily picks CSV")
    parser.add_argument("--marketed-slips", default=None,
                        help="Path to marketed_slips.csv to generate slip cards")
    parser.add_argument("--output-dir", default="data/output/graphics", 
                       help="Output directory for graphics (default: data/output/graphics)")
    
    args = parser.parse_args()

    if not args.csv and not args.marketed_slips:
        print("❌ Provide --csv or --marketed-slips (or both)")
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_files = []

    if args.marketed_slips:
        if not os.path.exists(args.marketed_slips):
            print(f"❌ marketed_slips file not found: {args.marketed_slips}")
            return 1
        print(f"🃏 Generating slip cards from {args.marketed_slips}...")
        generated_files += generate_slip_graphics(args.marketed_slips, output_dir)

    if args.csv:
        if not os.path.exists(args.csv):
            print(f"❌ CSV file not found: {args.csv}")
            return 1
        generated_files += generate_graphics(args.csv, output_dir)

    print(f"\n✅ Generated {len(generated_files)} graphics files:")
    for file_path in generated_files:
        print(f"   📸 {file_path}")
    print(f"\n🚀 Graphics ready for subscriber content!")
    return 0

if __name__ == "__main__":
    exit(main())