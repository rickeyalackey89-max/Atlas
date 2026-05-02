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
        'bg': '#0F172A',          # Deep navy (professional)
        'bg_gradient': '#1E293B',  # Lighter navy for gradient
        'accent': '#22C55E',      # Vibrant green
        'accent_glow': '#16A34A', # Darker green for glow
        'text': '#FFFFFF',        # White
        'subtitle': '#A7F3D0',    # Light green
        'card_bg': '#1E3A2E',     # Dark green card
        'court_line': '#34D399'   # Court line green
    },
    'STANDARD': {
        'bg': '#1E1B4B',          # Deep purple-blue
        'bg_gradient': '#312E81',  # Lighter for gradient
        'accent': '#3B82F6',      # Vibrant blue
        'accent_glow': '#2563EB', # Darker blue for glow
        'text': '#FFFFFF',        # White
        'subtitle': '#BFDBFE',    # Light blue
        'card_bg': '#1E40AF',     # Blue card
        'court_line': '#60A5FA'   # Court line blue
    },
    'DEMON': {
        'bg': '#7F1D1D',          # Deep red
        'bg_gradient': '#991B1B',  # Gradient red
        'accent': '#EF4444',      # Vibrant red
        'accent_glow': '#DC2626', # Darker red for glow
        'text': '#FFFFFF',        # White
        'subtitle': '#FECACA',    # Light red
        'card_bg': '#B91C1C',     # Red card
        'court_line': '#F87171'   # Court line red
    }
}

# Tier messaging - Enhanced
TIER_MESSAGING = {
    'GOBLIN': {
        'title': '🔒 LOCK PICKS',
        'subtitle': 'CHAMPIONSHIP CONFIDENCE',
        'emoji': '🔒',
        'tagline': 'MONEY IN THE BANK'
    },
    'STANDARD': {
        'title': '💎 SOLID PLAYS', 
        'subtitle': 'PLAYOFF WORTHY BETS',
        'emoji': '💎',
        'tagline': 'CONSISTENT WINNERS'
    },
    'DEMON': {
        'title': '🚀 MOON SHOTS',
        'subtitle': 'ALL-STAR SPECULATION',
        'emoji': '🚀',
        'tagline': 'HIGH RISK • BIG REWARDS'
    }
}

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
    
    # Gradient background
    for y in range(CARD_HEIGHT):
        # Create gradient from bg to bg_gradient
        ratio = y / CARD_HEIGHT
        # Simple gradient approximation
        draw.rectangle([0, y, CARD_WIDTH, y+1], fill=colors['bg'])
    
    # Court lines pattern
    line_color = colors['court_line']
    line_width = 4
    
    # Center court circle
    center_x, center_y = CARD_WIDTH // 2, CARD_HEIGHT // 2
    circle_radius = 120
    
    # Draw center circle (outline only)
    circle_box = [
        center_x - circle_radius,
        center_y - circle_radius,
        center_x + circle_radius,
        center_y + circle_radius
    ]
    draw.ellipse(circle_box, outline=line_color, width=line_width)
    
    # Free throw lanes (simplified)
    lane_width = 80
    lane_height = 200
    
    # Top lane
    lane_top_y = 100
    lane_left_x = center_x - lane_width // 2
    lane_right_x = center_x + lane_width // 2
    
    draw.rectangle([lane_left_x, lane_top_y, lane_right_x, lane_top_y + lane_height], 
                  outline=line_color, width=line_width)
    
    # Bottom lane
    lane_bottom_y = CARD_HEIGHT - 100 - lane_height
    draw.rectangle([lane_left_x, lane_bottom_y, lane_right_x, lane_bottom_y + lane_height], 
                  outline=line_color, width=line_width)
    
    # Three point arcs (partial)
    arc_radius = 180
    
    # Top arc
    arc_top_box = [
        center_x - arc_radius,
        50 - arc_radius,
        center_x + arc_radius,
        50 + arc_radius
    ]
    draw.arc(arc_top_box, start=0, end=180, fill=line_color, width=line_width)
    
    # Bottom arc  
    arc_bottom_box = [
        center_x - arc_radius,
        CARD_HEIGHT - 50 - arc_radius,
        center_x + arc_radius,
        CARD_HEIGHT - 50 + arc_radius
    ]
    draw.arc(arc_bottom_box, start=180, end=360, fill=line_color, width=line_width)
    
    # Corner court lines
    corner_length = 150
    
    # Top corners
    draw.line([0, corner_length, corner_length, corner_length], fill=line_color, width=line_width)
    draw.line([CARD_WIDTH - corner_length, corner_length, CARD_WIDTH, corner_length], 
              fill=line_color, width=line_width)
    
    # Bottom corners
    draw.line([0, CARD_HEIGHT - corner_length, corner_length, CARD_HEIGHT - corner_length], 
              fill=line_color, width=line_width)
    draw.line([CARD_WIDTH - corner_length, CARD_HEIGHT - corner_length, 
               CARD_WIDTH, CARD_HEIGHT - corner_length], 
              fill=line_color, width=line_width)

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
    
    colors = TIER_COLORS[tier]
    messaging = TIER_MESSAGING[tier]
    
    # Create image with NBA court background
    img = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), colors['bg'])
    draw_nba_court_background(img, colors)
    
    # Add semi-transparent overlay for better text readability
    overlay = Image.new('RGBA', (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle([0, 0, CARD_WIDTH, CARD_HEIGHT], 
                          fill=(0, 0, 0, 120))  # Semi-transparent black
    img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    
    draw = ImageDraw.Draw(img)
    
    # Fonts - Larger and bolder for more impact
    title_font = get_font(56, bold=True)
    subtitle_font = get_font(32, bold=True)
    tagline_font = get_font(24, bold=True)
    pick_font = get_font(36, bold=True)
    prob_font = get_font(42, bold=True)
    meta_font = get_font(22)
    
    # Header section with enhanced styling
    header_y = CARD_MARGIN
    
    # ATLAS Logo in top right corner
    logo_x = CARD_WIDTH - CARD_MARGIN - 60
    logo_y = header_y + 30
    draw_atlas_logo(draw, logo_x, logo_y, size=90, color_scheme='dark')
    
    # Title with glow effect
    title_pos = (CARD_WIDTH//2, header_y + 30)
    draw_text_with_glow(draw, title_pos, messaging['title'], 
                       title_font, colors['text'], colors['accent_glow'], glow_size=4)
    
    # Subtitle with glow
    subtitle_pos = (CARD_WIDTH//2, header_y + 90)
    draw_text_with_glow(draw, subtitle_pos, messaging['subtitle'],
                       subtitle_font, colors['accent'], '#000000', glow_size=2)
    
    # Tagline
    tagline_pos = (CARD_WIDTH//2, header_y + 130)
    draw.text(tagline_pos, messaging['tagline'],
             font=tagline_font, fill=colors['subtitle'], anchor="mm")
    
    # Date
    today = datetime.now().strftime("%B %d, %Y")
    draw.text((CARD_WIDTH//2, header_y + 160), today,
             font=meta_font, fill=colors['text'], anchor="mt")
    
    # Enhanced picks section
    picks_start_y = header_y + 220
    pick_height = 75
    
    for i, (_, pick) in enumerate(tier_picks.head(5).iterrows()):  # Show top 5
        y = picks_start_y + (i * pick_height)
        
        # Enhanced pick background with border
        pick_bg_x1 = CARD_MARGIN - 10
        pick_bg_x2 = CARD_WIDTH - CARD_MARGIN + 10
        pick_bg_y1 = y - 5
        pick_bg_y2 = y + pick_height - 15
        
        # Background with border
        draw.rounded_rectangle([pick_bg_x1, pick_bg_y1, pick_bg_x2, pick_bg_y2], 
                             radius=12, fill=colors['card_bg'], 
                             outline=colors['accent'], width=3)
        
        # Rank number with enhanced styling
        rank_text = f"#{int(pick['rank'])}"
        rank_pos = (CARD_MARGIN + 30, y + pick_height//2 - 5)
        draw_text_with_glow(draw, rank_pos, rank_text,
                           pick_font, colors['accent'], '#000000', glow_size=2)
        
        # Player name (larger and bolder)
        pick_text = f"{pick['player']}"
        if len(pick_text) > 15:
            pick_text = pick_text[:12] + "..."
        
        draw.text((CARD_MARGIN + 90, y + 8), pick_text,
                 font=pick_font, fill=colors['text'], anchor="lt")
        
        # Stat info with better formatting
        stat_text = f"{pick['stat']} {pick['direction']} {pick['line']}"
        draw.text((CARD_MARGIN + 90, y + 45), stat_text,
                 font=subtitle_font, fill=colors['subtitle'], anchor="lt")
        
        # Probability with glow effect
        prob_text = f"{pick['hit_probability_pct']}%"
        prob_pos = (CARD_WIDTH - CARD_MARGIN - 30, y + pick_height//2 - 5)
        draw_text_with_glow(draw, prob_pos, prob_text,
                           prob_font, colors['accent'], '#000000', glow_size=2)
    
    # Enhanced footer
    footer_y = CARD_HEIGHT - FOOTER_HEIGHT - 10
    
    # Footer background
    footer_bg_y1 = footer_y - 10
    footer_bg_y2 = CARD_HEIGHT - 10
    draw.rounded_rectangle([CARD_MARGIN//2, footer_bg_y1, CARD_WIDTH - CARD_MARGIN//2, footer_bg_y2], 
                         radius=15, fill=(0, 0, 0, 180))
    
    draw.text((CARD_WIDTH//2, footer_y + 15), "Powered by ATLAS 🌍💰",
             font=get_font(24, bold=True), fill=colors['accent'], anchor="mt")
    draw.text((CARD_WIDTH//2, footer_y + 45), f"Generated: {datetime.now().strftime('%I:%M %p')}",
             font=meta_font, fill=colors['text'], anchor="mt")
    
    # Save image
    output_path = output_dir / f"daily_{tier.lower()}_picks.png"
    img.save(output_path, "PNG", quality=95, optimize=True)
    
    return output_path

def create_summary_card(picks_df, output_dir):
    """Create a summary card with all tiers and NBA theming."""
    
    # Use GOBLIN colors for summary
    colors = TIER_COLORS['GOBLIN']
    
    # Create image with NBA court background
    img = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), colors['bg'])
    draw_nba_court_background(img, colors)
    
    # Add semi-transparent overlay for better text readability
    overlay = Image.new('RGBA', (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle([0, 0, CARD_WIDTH, CARD_HEIGHT], 
                          fill=(0, 0, 0, 140))  # Semi-transparent black
    img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    
    draw = ImageDraw.Draw(img)
    
    # Fonts - Enhanced sizing
    title_font = get_font(60, bold=True)
    subtitle_font = get_font(36, bold=True)
    tier_font = get_font(40, bold=True)
    count_font = get_font(30)
    
    # Header with enhanced styling
    header_y = CARD_MARGIN + 20
    
    # ATLAS Logo in top right corner
    logo_x = CARD_WIDTH - CARD_MARGIN - 60
    logo_y = header_y + 10
    draw_atlas_logo(draw, logo_x, logo_y, size=100, color_scheme='dark')
    
    # Title with glow
    title_pos = (CARD_WIDTH//2, header_y + 10)
    draw_text_with_glow(draw, title_pos, "🏀 DAILY NBA PICKS",
                       title_font, colors['text'], colors['accent_glow'], glow_size=5)
    
    # Subtitle
    today = datetime.now().strftime("%B %d, %Y")
    subtitle_pos = (CARD_WIDTH//2, header_y + 80)
    draw_text_with_glow(draw, subtitle_pos, today,
                       subtitle_font, colors['accent'], '#000000', glow_size=2)
    
    # Enhanced tier summaries
    summary_y = header_y + 160
    tier_height = 140
    
    for i, (tier, tier_colors) in enumerate(TIER_COLORS.items()):
        tier_picks = picks_df[picks_df['tier'] == tier]
        if tier_picks.empty:
            continue
            
        y = summary_y + (i * tier_height)
        
        # Enhanced tier background with glow border
        tier_bg_x1 = CARD_MARGIN - 15
        tier_bg_x2 = CARD_WIDTH - CARD_MARGIN + 15
        tier_bg_y1 = y - 10
        tier_bg_y2 = y + tier_height - 30
        
        # Glow effect background
        for offset in range(8, 0, -1):
            glow_alpha = max(20, 60 - offset * 5)
            glow_color = (*[int(tier_colors['accent'][1:3], 16), 
                           int(tier_colors['accent'][3:5], 16), 
                           int(tier_colors['accent'][5:7], 16)], glow_alpha)
            # Create glow effect (simplified)
        
        # Main tier background
        draw.rounded_rectangle([tier_bg_x1, tier_bg_y1, tier_bg_x2, tier_bg_y2],
                             radius=20, fill=tier_colors['bg'], 
                             outline=tier_colors['accent'], width=4)
        
        # Tier info with enhanced styling
        emoji = TIER_MESSAGING[tier]['emoji']
        tier_title = TIER_MESSAGING[tier]['title'].replace(emoji + ' ', '')
        
        # Emoji with glow
        emoji_pos = (CARD_MARGIN + 40, y + 20)
        draw_text_with_glow(draw, emoji_pos, emoji,
                           tier_font, tier_colors['accent'], '#000000', glow_size=3)
        
        # Title
        draw.text((CARD_MARGIN + 110, y + 20), tier_title,
                 font=tier_font, fill=tier_colors['accent'], anchor="lt")
        
        # Enhanced stats
        count = len(tier_picks)
        avg_prob = tier_picks['hit_probability_pct'].mean()
        
        stats_text = f"{count} PICKS • {avg_prob:.1f}% AVG CONFIDENCE"
        draw.text((CARD_MARGIN + 110, y + 65), stats_text,
                 font=count_font, fill=tier_colors['text'], anchor="lt")
        
        # Top pick preview with enhanced formatting
        if not tier_picks.empty:
            top_pick = tier_picks.iloc[0]
            preview_text = f"#{int(top_pick['rank'])} {top_pick['player']}"
            prob_text = f"({top_pick['hit_probability_pct']}%)"
            
            # Limit text length
            if len(preview_text) > 25:
                preview_text = preview_text[:22] + "..."
            
            draw.text((CARD_WIDTH - CARD_MARGIN - 40, y + 35), preview_text,
                     font=count_font, fill=tier_colors['text'], anchor="rt")
            draw.text((CARD_WIDTH - CARD_MARGIN - 40, y + 70), prob_text,
                     font=get_font(28, bold=True), fill=tier_colors['accent'], anchor="rt")
    
    # Enhanced footer
    footer_y = CARD_HEIGHT - 120
    
    # Footer background
    footer_bg_y1 = footer_y - 15
    footer_bg_y2 = CARD_HEIGHT - 15
    draw.rounded_rectangle([CARD_MARGIN//2, footer_bg_y1, CARD_WIDTH - CARD_MARGIN//2, footer_bg_y2], 
                         radius=20, fill=(0, 0, 0, 200))
    
    # Main footer text with glow
    main_text_pos = (CARD_WIDTH//2, footer_y + 20)
    draw_text_with_glow(draw, main_text_pos, "30 TOTAL PICKS • 10 PER TIER",
                       subtitle_font, colors['accent'], '#000000', glow_size=3)
    
    # Subscription call to action
    draw.text((CARD_WIDTH//2, footer_y + 55), "Powered by ATLAS 🌍💰 • Subscribe for Access",
             font=count_font, fill=colors['text'], anchor="mt")
    
    # Save
    output_path = output_dir / "daily_summary.png"
    img.save(output_path, "PNG", quality=95, optimize=True)
    
    return output_path
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
    parser.add_argument("--csv", required=True, help="Path to daily picks CSV")
    parser.add_argument("--output-dir", default="data/output/graphics", 
                       help="Output directory for graphics (default: data/output/graphics)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.csv):
        print(f"❌ CSV file not found: {args.csv}")
        return 1
    
    try:
        generated_files = generate_graphics(args.csv, args.output_dir)
        
        print(f"\\n✅ Generated {len(generated_files)} graphics files:")
        for file_path in generated_files:
            print(f"   📸 {file_path}")
        
        print(f"\\n🚀 Graphics ready for subscriber content!")
        
        return 0
        
    except Exception as e:
        print(f"❌ Error generating graphics: {e}")
        return 1

if __name__ == "__main__":
    exit(main())