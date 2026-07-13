"""Vector piece icons for Chess 3 (SPEC section 5, V3.3 styling).

Draws every piece as a colored body disc (with a dark outline, a darker rim
and a small highlight for a slightly 3D look) topped by a unique vector glyph
per piece type. Glyphs are drawn in near-white with dark outlines/details so
they read on both light and dark body colors. Pure ``pygame.draw`` primitives
only: no fonts, no image files. Works headless (SDL_VIDEODRIVER=dummy) on
plain Surfaces.

V3.3 adds theme-aware styling: the module-level ``STYLE`` dict (updated via
``set_style``) lets themes override the disc outline color (``rim``), add a
soft halo ring behind the disc (``glow``) and recolor the glyph linework
(``ink`` / ``glyph``). ``draw_piece`` consults ``STYLE`` on every call; the
defaults render exactly like the classic look. PLAYER_COLORS are never
touched by styling (player identification).

This is one of the only two modules allowed to import pygame (with main.py).
"""

import math
import os

import pygame

# Classic glyph palette (per spec): near-white fill, dark ink outline/detail.
GLYPH = (245, 245, 245)
INK = (25, 25, 30)

# Theme style overrides (SPEC V3.3). Mutate ONLY through set_style().
#   rim   : disc outline color override (None = classic dark ink)
#   glow  : soft halo ring behind the disc (None = off)
#   ink   : glyph linework / detail color
#   glyph : glyph fill color
STYLE = {"rim": None, "glow": None, "ink": INK, "glyph": GLYPH}

# Reset values used when set_style() is passed an explicit None.
_STYLE_DEFAULTS = {"rim": None, "glow": None, "ink": INK, "glyph": GLYPH}

# Sentinel: "argument not passed" for set_style / style-aware helpers.
_KEEP = object()


def set_style(rim=_KEEP, glow=_KEEP, ink=_KEEP, glyph=_KEEP):
    """Partially update STYLE (SPEC V3.3).

    Arguments that are not passed keep their current value. Passing an
    explicit ``None`` resets that field to its classic default (rim/glow
    off, ink/glyph classic colors), so
    ``set_style(rim=None, glow=None, ink=None, glyph=None)`` restores the
    default look. Color values are normalized to (r, g, b) int tuples.
    """
    for key, val in (("rim", rim), ("glow", glow),
                     ("ink", ink), ("glyph", glyph)):
        if val is _KEEP:
            continue
        if val is None:
            STYLE[key] = _STYLE_DEFAULTS[key]
        else:
            STYLE[key] = tuple(int(c) for c in val[:3])


def style_fingerprint():
    """Hashable snapshot of STYLE (cache keys, e.g. diagrams.py)."""
    return (STYLE["rim"], STYLE["glow"], STYLE["ink"], STYLE["glyph"])


# Player body colors in pid order: white, black, red, blue, gold, purple.
PLAYER_COLORS = [
    (238, 238, 238),
    (72, 72, 84),
    (214, 74, 74),
    (76, 118, 224),
    (232, 196, 66),
    (158, 84, 214),
]

# Canonical display order of the 20 piece types (v2 adds CT, VA, GO;
# v3 adds JG, SN, WD).
TYPE_ORDER = ["K", "Q", "R", "B", "N", "P",
              "CN", "AR", "WZ", "DR", "CH", "BM", "GH", "NE",
              "CT", "VA", "GO", "JG", "SN", "WD"]


# ---------------------------------------------------------------------------
# color / geometry helpers
# ---------------------------------------------------------------------------

def _darken(color, factor):
    """Return ``color`` scaled toward black by ``factor`` (0..1)."""
    return tuple(max(0, int(c * (1.0 - factor))) for c in color[:3])


def _lighten(color, factor):
    """Return ``color`` blended toward white by ``factor`` (0..1)."""
    return tuple(min(255, int(c + (255 - c) * factor)) for c in color[:3])


def _pt(cx, cy, s, x, y):
    """Map normalized glyph coords (x, y in ~[-1, 1]) to pixel coords."""
    return (int(round(cx + x * s)), int(round(cy + y * s)))


def _poly(surf, cx, cy, s, pts, fill=_KEEP, line=_KEEP, ow=1):
    """Filled polygon with an outline, in normalized glyph coordinates.

    ``fill``/``line`` default to the current STYLE glyph/ink colors.
    """
    if fill is _KEEP:
        fill = STYLE["glyph"]
    if line is _KEEP:
        line = STYLE["ink"]
    p = [_pt(cx, cy, s, x, y) for (x, y) in pts]
    pygame.draw.polygon(surf, fill, p)
    if line is not None and ow > 0:
        pygame.draw.polygon(surf, line, p, ow)


def _disc(surf, cx, cy, s, x, y, r, fill=_KEEP, line=_KEEP, ow=1):
    """Filled circle with an outline, in normalized glyph coordinates."""
    if fill is _KEEP:
        fill = STYLE["glyph"]
    if line is _KEEP:
        line = STYLE["ink"]
    c = _pt(cx, cy, s, x, y)
    rr = max(1, int(round(r * s)))
    pygame.draw.circle(surf, fill, c, rr)
    if line is not None and ow > 0:
        pygame.draw.circle(surf, line, c, rr, min(ow, rr))


def _stick(surf, cx, cy, s, a, b, w, fill=_KEEP, line=_KEEP, ow=1):
    """Thick line segment with a dark border (drawn as two stacked lines)."""
    if fill is _KEEP:
        fill = STYLE["glyph"]
    if line is _KEEP:
        line = STYLE["ink"]
    pa = _pt(cx, cy, s, *a)
    pb = _pt(cx, cy, s, *b)
    lw = max(1, int(round(w * s)))
    if line is not None and ow > 0:
        pygame.draw.line(surf, line, pa, pb, lw + 2 * ow)
    pygame.draw.line(surf, fill, pa, pb, lw)


def _ink_line(surf, cx, cy, s, a, b, w):
    """Plain dark detail line in normalized glyph coordinates."""
    pygame.draw.line(surf, STYLE["ink"], _pt(cx, cy, s, *a),
                     _pt(cx, cy, s, *b), max(1, w))


def _ink_disc(surf, cx, cy, s, x, y, r):
    """Plain dark filled circle in normalized glyph coordinates."""
    pygame.draw.circle(surf, STYLE["ink"], _pt(cx, cy, s, x, y),
                       max(1, int(round(r * s))))


def _ink_poly(surf, cx, cy, s, pts):
    """Plain dark filled polygon in normalized glyph coordinates."""
    pygame.draw.polygon(surf, STYLE["ink"],
                        [_pt(cx, cy, s, x, y) for (x, y) in pts])


def _star_pts(x, y, r_out, r_in, points=5):
    """Point list for a star centered at (x, y) in normalized coords."""
    pts = []
    for k in range(points * 2):
        ang = -math.pi / 2 + k * math.pi / points
        r = r_out if k % 2 == 0 else r_in
        pts.append((x + r * math.cos(ang), y + r * math.sin(ang)))
    return pts


def _arc_band_pts(center, r_out, r_in, a0, a1, steps=12):
    """Point list for a crescent (thick arc) between two radii."""
    cx0, cy0 = center
    pts = []
    for k in range(steps + 1):
        a = a0 + (a1 - a0) * k / steps
        pts.append((cx0 + r_out * math.cos(a), cy0 + r_out * math.sin(a)))
    for k in range(steps + 1):
        a = a1 - (a1 - a0) * k / steps
        pts.append((cx0 + r_in * math.cos(a), cy0 + r_in * math.sin(a)))
    return pts


# ---------------------------------------------------------------------------
# per-type glyphs (normalized coords: x right, y down, roughly [-1, 1])
# ---------------------------------------------------------------------------

def _g_king(surf, cx, cy, s, ow):
    """Crown with a cross on top."""
    cross = [(-0.09, -0.95), (0.09, -0.95), (0.09, -0.84), (0.30, -0.84),
             (0.30, -0.66), (0.09, -0.66), (0.09, -0.46), (-0.09, -0.46),
             (-0.09, -0.66), (-0.30, -0.66), (-0.30, -0.84), (-0.09, -0.84)]
    _poly(surf, cx, cy, s, cross, ow=ow)
    crown = [(-0.72, 0.55), (-0.72, -0.30), (-0.38, -0.05), (0.0, -0.42),
             (0.38, -0.05), (0.72, -0.30), (0.72, 0.55)]
    _poly(surf, cx, cy, s, crown, ow=ow)
    _ink_line(surf, cx, cy, s, (-0.70, 0.30), (0.70, 0.30), ow)


def _g_queen(surf, cx, cy, s, ow):
    """Spiky three-point crown with tip balls and a central orb."""
    crown = [(-0.78, 0.55), (-0.66, -0.50), (-0.34, -0.02), (0.0, -0.66),
             (0.34, -0.02), (0.66, -0.50), (0.78, 0.55)]
    _poly(surf, cx, cy, s, crown, ow=ow)
    for (x, y) in ((-0.66, -0.62), (0.0, -0.80), (0.66, -0.62)):
        _disc(surf, cx, cy, s, x, y, 0.10, ow=ow)
    _disc(surf, cx, cy, s, 0.0, 0.26, 0.15, ow=ow)  # orb on the band


def _g_rook(surf, cx, cy, s, ow):
    """Castle tower with battlements and a dark door."""
    tower = [(-0.60, 0.60), (-0.60, -0.60), (-0.34, -0.60), (-0.34, -0.32),
             (-0.12, -0.32), (-0.12, -0.60), (0.12, -0.60), (0.12, -0.32),
             (0.34, -0.32), (0.34, -0.60), (0.60, -0.60), (0.60, 0.60)]
    _poly(surf, cx, cy, s, tower, ow=ow)
    _ink_poly(surf, cx, cy, s,
              [(-0.15, 0.60), (0.15, 0.60), (0.15, 0.14), (-0.15, 0.14)])
    _ink_line(surf, cx, cy, s, (-0.58, 0.0), (0.58, 0.0), ow)


def _g_bishop(surf, cx, cy, s, ow):
    """Mitre with a vertical slit, top ball and base bar."""
    _poly(surf, cx, cy, s,
          [(-0.58, 0.44), (0.58, 0.44), (0.58, 0.62), (-0.58, 0.62)], ow=ow)
    mitre = [(0.0, -0.70), (0.30, -0.36), (0.46, 0.06), (0.46, 0.40),
             (-0.46, 0.40), (-0.46, 0.06), (-0.30, -0.36)]
    _poly(surf, cx, cy, s, mitre, ow=ow)
    _disc(surf, cx, cy, s, 0.0, -0.82, 0.10, ow=ow)
    _ink_line(surf, cx, cy, s, (0.0, -0.56), (0.0, -0.08), max(1, ow + 1))


def _g_knight(surf, cx, cy, s, ow):
    """Horse head in left-facing profile with ear and eye."""
    head = [(-0.78, -0.05), (-0.48, -0.30), (-0.22, -0.50), (-0.14, -0.84),
            (0.10, -0.58), (0.38, -0.36), (0.54, -0.02), (0.58, 0.58),
            (-0.28, 0.58), (-0.20, 0.22), (-0.52, 0.16), (-0.78, 0.10)]
    _poly(surf, cx, cy, s, head, ow=ow)
    _ink_disc(surf, cx, cy, s, -0.34, -0.16, 0.07)


def _g_pawn(surf, cx, cy, s, ow):
    """Small ball on a neck and flared base."""
    _poly(surf, cx, cy, s,
          [(-0.17, -0.02), (0.17, -0.02), (0.26, 0.36), (-0.26, 0.36)], ow=ow)
    _poly(surf, cx, cy, s,
          [(-0.50, 0.62), (0.50, 0.62), (0.36, 0.32), (-0.36, 0.32)], ow=ow)
    _disc(surf, cx, cy, s, 0.0, -0.32, 0.33, ow=ow)


def _g_cannon(surf, cx, cy, s, ow):
    """Angled cannon barrel over a spoked wheel."""
    barrel = [(-0.199, 0.237), (-0.401, -0.027), (0.519, -0.717),
              (0.721, -0.443)]
    _poly(surf, cx, cy, s, barrel, ow=ow)
    _ink_line(surf, cx, cy, s, (0.611, -0.363), (0.409, -0.637), max(1, ow))
    _disc(surf, cx, cy, s, -0.16, 0.34, 0.30, ow=ow)
    _ink_line(surf, cx, cy, s, (-0.42, 0.34), (0.10, 0.34), max(1, ow))
    _ink_line(surf, cx, cy, s, (-0.16, 0.08), (-0.16, 0.60), max(1, ow))
    _ink_disc(surf, cx, cy, s, -0.16, 0.34, 0.07)


def _g_archer(surf, cx, cy, s, ow):
    """Bow arc with string plus a nocked arrow."""
    a0, a1 = -1.15, 1.15
    band = _arc_band_pts((-0.42, 0.0), 0.92, 0.78, a0, a1)
    _poly(surf, cx, cy, s, band, ow=ow)
    tip_t = (-0.42 + 0.85 * math.cos(a0), 0.85 * math.sin(a0))
    tip_b = (-0.42 + 0.85 * math.cos(a1), 0.85 * math.sin(a1))
    _ink_line(surf, cx, cy, s, tip_t, tip_b, max(1, ow))
    _stick(surf, cx, cy, s, (-0.60, 0.0), (0.52, 0.0), 0.10, ow=ow)
    _poly(surf, cx, cy, s, [(0.86, 0.0), (0.48, -0.18), (0.48, 0.18)], ow=ow)
    _ink_line(surf, cx, cy, s, (-0.60, 0.0), (-0.80, -0.16), max(1, ow))
    _ink_line(surf, cx, cy, s, (-0.60, 0.0), (-0.80, 0.16), max(1, ow))


def _g_wizard(surf, cx, cy, s, ow):
    """Pointed hat with a flopped tip, wide brim, and a magic star."""
    _poly(surf, cx, cy, s,
          [(-0.80, 0.30), (0.80, 0.30), (0.68, 0.48), (-0.68, 0.48)], ow=ow)
    cone = [(-0.50, 0.30), (0.50, 0.30), (0.18, -0.28), (0.48, -0.72),
            (0.00, -0.34)]
    _poly(surf, cx, cy, s, cone, ow=ow)
    _poly(surf, cx, cy, s, _star_pts(-0.48, -0.48, 0.22, 0.09), ow=ow)


def _g_dragon(surf, cx, cy, s, ow):
    """Pair of bat wings around a small body with a spade-tipped tail."""
    wing_l = [(-0.05, -0.02), (-0.26, -0.44), (-0.85, -0.62), (-0.58, -0.34),
              (-0.70, -0.05), (-0.40, 0.06), (-0.36, 0.32), (-0.05, 0.30)]
    wing_r = [(-x, y) for (x, y) in wing_l]
    _poly(surf, cx, cy, s, wing_l, ow=ow)
    _poly(surf, cx, cy, s, wing_r, ow=ow)
    _disc(surf, cx, cy, s, 0.0, 0.10, 0.17, ow=ow)
    _stick(surf, cx, cy, s, (0.0, 0.22), (0.13, 0.48), 0.08, ow=ow)
    _stick(surf, cx, cy, s, (0.13, 0.48), (0.0, 0.68), 0.08, ow=ow)
    _poly(surf, cx, cy, s,
          [(-0.04, 0.88), (-0.16, 0.62), (0.14, 0.66)], ow=ow)


def _g_champion(surf, cx, cy, s, ow):
    """Heater shield bearing a dark chevron."""
    shield = [(-0.55, -0.55), (0.55, -0.55), (0.55, 0.02), (0.0, 0.62),
              (-0.55, 0.02)]
    _poly(surf, cx, cy, s, shield, ow=ow)
    _ink_poly(surf, cx, cy, s,
              [(-0.36, -0.22), (0.0, 0.08), (0.36, -0.22), (0.36, 0.02),
               (0.0, 0.32), (-0.36, 0.02)])


def _g_bomber(surf, cx, cy, s, ow):
    """Round bomb with cap, fuse, and a spark burst."""
    _disc(surf, cx, cy, s, 0.26, -0.30, 0.13, ow=ow)       # cap
    _stick(surf, cx, cy, s, (0.30, -0.34), (0.46, -0.54), 0.09, ow=ow)
    _disc(surf, cx, cy, s, -0.05, 0.16, 0.46, ow=ow)       # bomb ball
    spark = (0.55, -0.65)
    for k in range(5):
        ang = math.radians(-160 + k * 55)
        end = (spark[0] + 0.22 * math.cos(ang),
               spark[1] + 0.22 * math.sin(ang))
        _stick(surf, cx, cy, s, spark, end, 0.06, ow=ow)


def _g_ghost(surf, cx, cy, s, ow):
    """Sheet with a domed top, wavy bottom, and two dark eyes."""
    sheet = [(-0.52, -0.05), (-0.45, -0.35), (-0.26, -0.57), (0.0, -0.65),
             (0.26, -0.57), (0.45, -0.35), (0.52, -0.05), (0.52, 0.44),
             (0.35, 0.20), (0.17, 0.48), (0.0, 0.22), (-0.17, 0.48),
             (-0.35, 0.20), (-0.52, 0.44)]
    _poly(surf, cx, cy, s, sheet, ow=ow)
    _ink_disc(surf, cx, cy, s, -0.18, -0.25, 0.09)
    _ink_disc(surf, cx, cy, s, 0.18, -0.25, 0.09)


def _g_necromancer(surf, cx, cy, s, ow):
    """Skull: cranium, jaw with teeth, eye sockets, nose hole."""
    _poly(surf, cx, cy, s,
          [(-0.28, 0.10), (0.28, 0.10), (0.24, 0.56), (-0.24, 0.56)], ow=ow)
    _disc(surf, cx, cy, s, 0.0, -0.14, 0.46, ow=ow)
    for x in (-0.12, 0.0, 0.12):
        _ink_line(surf, cx, cy, s, (x, 0.34), (x, 0.54), max(1, ow))
    _ink_disc(surf, cx, cy, s, -0.19, -0.18, 0.11)
    _ink_disc(surf, cx, cy, s, 0.19, -0.18, 0.11)
    _ink_poly(surf, cx, cy, s, [(0.0, 0.0), (-0.07, 0.14), (0.07, 0.14)])


def _g_catapult(surf, cx, cy, s, ow):
    """Siege catapult: wheeled frame, angled throwing arm, flying boulder."""
    # base beam
    _poly(surf, cx, cy, s,
          [(-0.74, 0.38), (0.62, 0.38), (0.62, 0.56), (-0.74, 0.56)], ow=ow)
    # A-frame support
    _poly(surf, cx, cy, s,
          [(-0.46, 0.40), (-0.12, -0.14), (0.26, 0.40)], ow=ow)
    # throwing arm, hinged at the frame, swung up-right
    _stick(surf, cx, cy, s, (-0.36, 0.32), (0.52, -0.52), 0.13, ow=ow)
    # cup crossbar at the arm tip
    _stick(surf, cx, cy, s, (0.38, -0.66), (0.68, -0.38), 0.10, ow=ow)
    # boulder just released
    _disc(surf, cx, cy, s, 0.24, -0.84, 0.16, ow=ow)
    # wheels with dark hubs
    for wx in (-0.50, 0.38):
        _disc(surf, cx, cy, s, wx, 0.60, 0.22, ow=ow)
        _ink_disc(surf, cx, cy, s, wx, 0.60, 0.07)


def _g_valkyrie(surf, cx, cy, s, ow):
    """Winged helmet: domed helm with nose guard, flanked by a wing pair."""
    wing_l = [(-0.32, -0.10), (-0.95, -0.55), (-0.62, -0.26), (-0.90, -0.14),
              (-0.56, -0.06), (-0.76, 0.14), (-0.34, 0.16)]
    wing_r = [(-x, y) for (x, y) in wing_l]
    _poly(surf, cx, cy, s, wing_l, ow=ow)
    _poly(surf, cx, cy, s, wing_r, ow=ow)
    # helm dome
    dome = [(-0.40, 0.30), (-0.36, -0.10), (-0.20, -0.36), (0.0, -0.46),
            (0.20, -0.36), (0.36, -0.10), (0.40, 0.30)]
    _poly(surf, cx, cy, s, dome, ow=ow)
    # brim and nose guard
    _poly(surf, cx, cy, s,
          [(-0.46, 0.28), (0.46, 0.28), (0.46, 0.42), (-0.46, 0.42)], ow=ow)
    _poly(surf, cx, cy, s,
          [(-0.07, 0.42), (0.07, 0.42), (0.07, 0.72), (-0.07, 0.72)], ow=ow)
    _ink_line(surf, cx, cy, s, (0.0, -0.44), (0.0, -0.14), max(1, ow))


def _g_golem(surf, cx, cy, s, ow):
    """Blocky stone golem: square head, slab torso, hanging arm blocks."""
    # arm blocks (drawn first so the torso overlaps them)
    _poly(surf, cx, cy, s,
          [(-0.82, -0.14), (-0.52, -0.14), (-0.52, 0.48), (-0.82, 0.48)],
          ow=ow)
    _poly(surf, cx, cy, s,
          [(0.52, -0.14), (0.82, -0.14), (0.82, 0.48), (0.52, 0.48)], ow=ow)
    # torso slab
    _poly(surf, cx, cy, s,
          [(-0.50, -0.20), (0.50, -0.20), (0.50, 0.64), (-0.50, 0.64)], ow=ow)
    # head block
    _poly(surf, cx, cy, s,
          [(-0.32, -0.74), (0.32, -0.74), (0.32, -0.14), (-0.32, -0.14)],
          ow=ow)
    # deep-set square eyes
    _ink_poly(surf, cx, cy, s,
              [(-0.23, -0.52), (-0.09, -0.52), (-0.09, -0.36), (-0.23, -0.36)])
    _ink_poly(surf, cx, cy, s,
              [(0.09, -0.52), (0.23, -0.52), (0.23, -0.36), (0.09, -0.36)])
    # cracks in the stone
    _ink_line(surf, cx, cy, s, (-0.30, 0.10), (-0.12, 0.26), max(1, ow))
    _ink_line(surf, cx, cy, s, (-0.12, 0.26), (-0.26, 0.46), max(1, ow))
    _ink_line(surf, cx, cy, s, (0.18, 0.06), (0.32, 0.24), max(1, ow))
    _ink_line(surf, cx, cy, s, (0.32, 0.24), (0.22, 0.44), max(1, ow))


def _g_juggernaut(surf, cx, cy, s, ow):
    """Charging bull head: swept horns, broad skull, flared nostrils."""
    # horns first so the skull overlaps their bases
    horn_l = [(-0.30, -0.35), (-0.62, -0.50), (-0.84, -0.86), (-0.92, -0.52),
              (-0.72, -0.18), (-0.40, -0.08)]
    horn_r = [(-x, y) for (x, y) in horn_l]
    _poly(surf, cx, cy, s, horn_l, ow=ow)
    _poly(surf, cx, cy, s, horn_r, ow=ow)
    # skull: broad brow narrowing into the muzzle
    head = [(-0.44, -0.52), (0.44, -0.52), (0.54, -0.02), (0.30, 0.42),
            (0.16, 0.66), (-0.16, 0.66), (-0.30, 0.42), (-0.54, -0.02)]
    _poly(surf, cx, cy, s, head, ow=ow)
    # brow line
    _ink_line(surf, cx, cy, s, (-0.38, -0.30), (0.38, -0.30), max(1, ow))
    # eyes
    _ink_disc(surf, cx, cy, s, -0.24, -0.10, 0.08)
    _ink_disc(surf, cx, cy, s, 0.24, -0.10, 0.08)
    # flared nostrils on the muzzle
    _ink_disc(surf, cx, cy, s, -0.12, 0.46, 0.07)
    _ink_disc(surf, cx, cy, s, 0.12, 0.46, 0.07)


def _g_sniper(surf, cx, cy, s, ow):
    """Crossbow (unlike AR's simple bow): prod + string over a straight
    stock with a shoulder butt, a nocked bolt, and a scope with lens dot."""
    a0, a1 = math.radians(-118), math.radians(-62)
    band = _arc_band_pts((0.0, 0.62), 1.30, 1.16, a0, a1)
    _poly(surf, cx, cy, s, band, ow=ow)                      # bow prod
    tip_l = (1.23 * math.cos(a0), 0.62 + 1.23 * math.sin(a0))
    tip_r = (-tip_l[0], tip_l[1])
    _ink_line(surf, cx, cy, s, tip_l, tip_r, max(1, ow))     # string
    _stick(surf, cx, cy, s, (0.0, -0.58), (0.0, 0.55), 0.14, ow=ow)  # stock
    _poly(surf, cx, cy, s,
          [(-0.20, 0.50), (0.20, 0.50), (0.26, 0.80), (-0.26, 0.80)],
          ow=ow)                                             # shoulder butt
    _poly(surf, cx, cy, s,
          [(0.0, -0.94), (-0.15, -0.64), (0.15, -0.64)], ow=ow)  # bolt head
    # side-mounted scope with a dark lens dot
    _stick(surf, cx, cy, s, (0.07, 0.08), (0.24, 0.08), 0.06, ow=ow)
    _disc(surf, cx, cy, s, 0.36, 0.08, 0.15, ow=ow)
    _ink_disc(surf, cx, cy, s, 0.36, 0.08, 0.06)


def _g_warden(surf, cx, cy, s, ow):
    """Tower shield (tall, pointed foot, spine + rivets) under a small
    protective aura arc."""
    # aura arc floating over the shield
    band = _arc_band_pts((0.0, 0.10), 1.02, 0.88,
                         math.radians(-150), math.radians(-30))
    _poly(surf, cx, cy, s, band, ow=ow)
    # tall tower shield with a pointed foot
    shield = [(-0.42, -0.58), (0.42, -0.58), (0.46, 0.34), (0.0, 0.72),
              (-0.46, 0.34)]
    _poly(surf, cx, cy, s, shield, ow=ow)
    # center spine + cross band
    _ink_line(surf, cx, cy, s, (0.0, -0.52), (0.0, 0.62), max(1, ow))
    _ink_line(surf, cx, cy, s, (-0.40, -0.10), (0.40, -0.10), max(1, ow))
    # rivets
    _ink_disc(surf, cx, cy, s, -0.26, -0.36, 0.06)
    _ink_disc(surf, cx, cy, s, 0.26, -0.36, 0.06)


_GLYPHS = {
    "K": _g_king,
    "Q": _g_queen,
    "R": _g_rook,
    "B": _g_bishop,
    "N": _g_knight,
    "P": _g_pawn,
    "CN": _g_cannon,
    "AR": _g_archer,
    "WZ": _g_wizard,
    "DR": _g_dragon,
    "CH": _g_champion,
    "BM": _g_bomber,
    "GH": _g_ghost,
    "NE": _g_necromancer,
    "CT": _g_catapult,
    "VA": _g_valkyrie,
    "GO": _g_golem,
    "JG": _g_juggernaut,
    "SN": _g_sniper,
    "WD": _g_warden,
}


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def draw_piece(surface, ptype, body_color, size, center):
    """Draw piece ``ptype`` onto ``surface`` fitting a circle of diameter ~``size``.

    Renders a filled disc in ``body_color`` with a dark outline, a subtly
    darker rim (thicker toward the bottom-right) and a small top-left
    highlight for a slightly 3D look, then the type's unique near-white
    glyph with dark outline/details on top.

    The current STYLE (V3.3) is consulted on every call: ``glow`` (when
    set) paints a soft halo ring behind the disc, ``rim`` overrides the
    disc outline color, and ``ink``/``glyph`` recolor the glyph linework.
    With the default STYLE the output is exactly the classic look.

    Args:
        surface: any pygame.Surface (no display required).
        ptype: one of the 20 type ids ("K", "Q", ..., "JG", "SN", "WD").
        body_color: (r, g, b) body color, e.g. an entry of PLAYER_COLORS.
        size: target diameter in pixels (glyphs stay readable down to ~24).
        center: (x, y) pixel center of the piece.

    Raises:
        ValueError: if ``ptype`` is not a known piece type.
    """
    if ptype not in _GLYPHS:
        raise ValueError("unknown piece type: %r" % (ptype,))
    cx = int(round(center[0]))
    cy = int(round(center[1]))
    R = max(4, int(size) // 2)
    ow = max(1, int(round(size / 22)))
    body = tuple(int(c) for c in body_color[:3])

    # soft halo ring behind the disc (theme glow, V3.3) — a 2px bright
    # ring plus a 1px darker outer edge; the body disc covers the middle
    glow = STYLE["glow"]
    if glow is not None:
        pygame.draw.circle(surface, _darken(glow, 0.45), (cx, cy), R + 3)
        pygame.draw.circle(surface, glow, (cx, cy), R + 2)

    # body disc: outline (rim override or classic dark), darker rim,
    # main fill nudged up-left (3D rim)
    rim = STYLE["rim"]
    pygame.draw.circle(surface, INK if rim is None else rim, (cx, cy), R)
    pygame.draw.circle(surface, _darken(body, 0.35), (cx, cy), R - ow)
    rim_w = max(1, int(round(R * 0.14)))
    shift = max(0, int(rim_w * 0.7))
    pygame.draw.circle(surface, body, (cx - shift, cy - shift),
                       max(1, R - ow - rim_w))

    # small top-left highlight
    hi_rect = pygame.Rect(0, 0, max(2, int(round(R * 0.50))),
                          max(2, int(round(R * 0.34))))
    hi_rect.center = (cx - int(round(R * 0.34)), cy - int(round(R * 0.40)))
    pygame.draw.ellipse(surface, _lighten(body, 0.45), hi_rect)

    # glyph
    _GLYPHS[ptype](surface, cx, cy, R * 0.68, ow)


def render_all_preview(cell=48):
    """Render a grid of all 20 piece types in all 6 player colors.

    Columns are the 20 types in TYPE_ORDER; rows are the 6 PLAYER_COLORS.
    Cells alternate dark/light backgrounds so glyph readability can be
    checked on both. Used by the help screen and for manual eyeballing.

    Returns:
        A pygame.Surface of size (20 * cell, 6 * cell).
    """
    cols = len(TYPE_ORDER)
    rows = len(PLAYER_COLORS)
    surf = pygame.Surface((cols * cell, rows * cell))
    dark_bg = (58, 58, 66)
    light_bg = (198, 200, 206)
    for row, color in enumerate(PLAYER_COLORS):
        for col, ptype in enumerate(TYPE_ORDER):
            bg = dark_bg if (row + col) % 2 == 0 else light_bg
            surf.fill(bg, pygame.Rect(col * cell, row * cell, cell, cell))
            draw_piece(surf, ptype, color, int(cell * 0.82),
                       (col * cell + cell // 2, row * cell + cell // 2))
    return surf


if __name__ == "__main__":
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    _out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "icons_preview.png")
    pygame.image.save(render_all_preview(64), _out)
    print("saved", _out)
    pygame.quit()
