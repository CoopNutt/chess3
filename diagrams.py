"""Movement diagrams for the help screen (SPEC V2.4).

``movement_diagram(ptype, width)`` renders a mini hexagon board (radius 3,
same pointy-top math and cell shade trio as the game board) with the piece
at the center and its legal moves marked:

    green dot       = quiet move
    red ring        = capture
    red crosshair   = shoot target
    green plus      = necromancer raise

Every marker comes from REAL engine movegen on a small demo GameState —
nothing is hand-placed. Per-type demo setups add gray enemy pieces
(owner 1, and for the juggernaut one blue friendly blocker) so signature
abilities show: the cannon gets a screen + a target beyond it,
archer/catapult get targets at their shoot range, the sniper gets diagonal
shoot targets plus a blocker it shoots over, the juggernaut gets an enemy
in charge range and a friendly blocker its charge stops short of, the
ghost gets a mid-ray blocker, the bomber gets a capture target (with the
6 explosion cells hatched orange — decoration mandated by the spec,
derived from the movegen capture), and the necromancer gets one lost pawn
so raise markers appear. The warden diagram is its bare 12 king-steps.
Pawns use seat edge 0, so "forward" is up.

Surfaces are cached per (ptype, width, icons style fingerprint) — V3.3
theme styling changes the pieces, so a style change misses the old cache
entries; main.set_theme additionally calls clear_cache(). Works headless
(SDL_VIDEODRIVER=dummy); imports engine + icons only, no file assets.
"""

import math

import pygame

import engine
import icons

SQ3 = math.sqrt(3)

# Radius of the mini board / marker window around the demo piece.
WINDOW_RADIUS = 3

# Types whose signature range does not fit in the default window: the
# sniper shoots 2 diagonal steps = hex distance 4.
_WINDOW_OVERRIDES = {"SN": 4}


def window_radius(ptype):
    """Mini-board radius used for `ptype`'s diagram (default 3)."""
    return _WINDOW_OVERRIDES.get(ptype, WINDOW_RADIUS)

# Same classic cell shade trio as the in-game board.
CELL_SHADES = [(216, 183, 143), (191, 150, 104), (168, 123, 78)]

# Demo piece body = player color index 3 (blue); enemies are neutral gray.
DEMO_COLOR_INDEX = 3
ENEMY_COLOR = (150, 150, 155)

# Marker palette (matches main.py's board markers).
QUIET_COLOR = (90, 200, 110)
CAPTURE_COLOR = (235, 90, 90)
SHOOT_COLOR = (240, 110, 110)
RAISE_COLOR = (120, 220, 130)
HATCH_COLOR = (255, 150, 60)

# Where the demo piece stands (origin of the radius-6 demo board).
_CENTER = (0, 0)

# Per-type gray enemy pieces (cell offset from the demo piece, type).
# These exist so each signature ability produces markers via movegen.
_DEMO_ENEMIES = {
    # screen on the ray, target right beyond it -> jump capture shows
    "CN": (((2, 0), "P"), ((3, 0), "P")),
    # blocker on the intermediate cell + targets at exactly range 2
    "AR": (((1, 0), "P"), ((2, 0), "P"), ((-2, 0), "P")),
    # blocker mid-ray + targets at exactly range 3
    "CT": (((2, 0), "P"), ((3, 0), "P"), ((0, -3), "P")),
    # blocker on the first diagonal cell of a ray (ghost phases through)
    "GH": (((2, -1), "P"),),
    # one capture target; its 6 neighbors get the orange explosion hatch
    "BM": (((2, 0), "P"),),
    # enemies in charge range: the charge may only stop ON them (capture)
    "JG": (((2, 0), "P"), ((-3, 0), "P")),
    # blocker on the first diag step + targets at exactly 2 diag steps
    # (the sniper shoots straight over the blocker)
    "SN": (((1, 1), "P"), ((2, 2), "P"), ((-4, 2), "P")),
}

# Per-type friendly pieces (owner 0, drawn in the demo blue). The
# juggernaut's charge stops on the last empty cell BEFORE a friendly
# blocker — that quiet endpoint is the diagram's signature marker.
_DEMO_FRIENDS = {
    "JG": (((0, 3), "P"),),
}

_CACHE = {}


def clear_cache():
    """Drop every cached diagram surface (main.set_theme calls this)."""
    _CACHE.clear()


def demo_state(ptype):
    """Build the small 2-player demo GameState used for `ptype`'s diagram.

    The board is cleared, the demo piece (owner 0, moved=True, seat edge 0)
    is placed at the center, plus the per-type gray enemies (owner 1) and
    friendly blockers (owner 0). The necromancer gets one lost pawn so its
    raise moves exist.
    """
    if ptype not in engine.PIECE_NAMES:
        raise ValueError("unknown piece type: %r" % (ptype,))
    gs = engine.GameState.new_game([(0, "Demo"), (1, "Rival")])
    gs.board.clear()
    gs.lost[0] = []
    gs.lost[1] = []
    gs.log = []
    gs.board[_CENTER] = engine.Piece(ptype, 0, True)
    for cell, t in _DEMO_ENEMIES.get(ptype, ()):
        gs.board[cell] = engine.Piece(t, 1, True)
    for cell, t in _DEMO_FRIENDS.get(ptype, ()):
        gs.board[cell] = engine.Piece(t, 0, True)
    if ptype == "NE":
        gs.lost[0].append("P")
    return gs


def demo_moves(ptype):
    """The engine movegen output the diagram for `ptype` is drawn from."""
    return demo_state(ptype).legal_moves(_CENTER)


def _hex_points(cx, cy, s, scale=0.985):
    """Corner points of a pointy-top hex cell (same math as the game)."""
    pts = []
    for k in range(6):
        a = math.radians(60 * k - 30)
        pts.append((cx + s * scale * math.cos(a),
                    cy + s * scale * math.sin(a)))
    return pts


def _draw_hatch(surf, cx, cy, s):
    """Orange diagonal hatching + outline marking an explosion cell."""
    w = max(2, int(round(s * 0.09)))
    pygame.draw.polygon(surf, HATCH_COLOR, _hex_points(cx, cy, s, 0.88), w)
    r_in = s * SQ3 / 2 * 0.82        # inscribed-circle radius, slightly shrunk
    ux, uy = math.cos(math.radians(45)), math.sin(math.radians(45))
    nx, ny = -uy, ux
    for t in (-0.62, -0.21, 0.21, 0.62):
        d = t * r_in
        half = math.sqrt(max(0.0, r_in * r_in - d * d))
        mx, my = cx + nx * d, cy + ny * d
        pygame.draw.line(surf, HATCH_COLOR,
                         (mx - ux * half, my - uy * half),
                         (mx + ux * half, my + uy * half), w)


def movement_diagram(ptype, width=240):
    """Render (and cache) the movement diagram for `ptype`.

    Returns a pygame.Surface `width` px wide (height is proportional,
    roughly 0.91 * width) with per-pixel alpha outside the mini board.
    Treat the returned surface as read-only — it is shared via the cache.
    The cache key includes the current icons style fingerprint (V3.3), so
    themed restyles never serve stale surfaces.
    """
    key = (ptype, int(width), icons.style_fingerprint())
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    width = int(width)
    if width < 40:
        raise ValueError("diagram width too small: %d" % width)

    gs = demo_state(ptype)
    moves = gs.legal_moves(_CENTER)
    window = engine.board_cells(window_radius(ptype))

    # layout: same pointy-top axial -> pixel math as the game board
    xs = [SQ3 * (q + r / 2.0) for q, r in window]
    ys = [1.5 * r for _q, r in window]
    w_units = (max(xs) - min(xs)) + SQ3
    h_units = (max(ys) - min(ys)) + 2.0
    height = int(math.ceil(width * h_units / w_units))
    s = min(width / w_units, height / h_units) * 0.99
    ox = width / 2.0
    oy = height / 2.0

    def to_px(cell):
        q, r = cell
        return (ox + SQ3 * (q + r / 2.0) * s, oy + 1.5 * r * s)

    surf = pygame.Surface((width, height), pygame.SRCALPHA)

    # cells
    for cell in sorted(window):
        cx, cy = to_px(cell)
        shade = CELL_SHADES[(cell[0] - cell[1]) % 3]
        pygame.draw.polygon(surf, shade, _hex_points(cx, cy, s))

    # bomber explosion preview: hatch the 6 neighbors of each movegen
    # capture target (the explosion is centered on the landing cell)
    if ptype == "BM":
        for mv in moves:
            if mv.kind != "move" or mv.to not in gs.board:
                continue
            for dq, dr in engine.ORTHO:
                t = (mv.to[0] + dq, mv.to[1] + dr)
                if t in window:
                    _draw_hatch(surf, *to_px(t), s=s)

    # pieces: gray demo enemies + blue friendlies, then the demo piece
    piece_size = int(s * 1.15)
    for cell, pc in sorted(gs.board.items()):
        if cell == _CENTER or cell not in window:
            continue
        cx, cy = to_px(cell)
        color = (icons.PLAYER_COLORS[DEMO_COLOR_INDEX] if pc.owner == 0
                 else ENEMY_COLOR)
        icons.draw_piece(surf, pc.type, color, piece_size,
                         (int(cx), int(cy)))
    ccx, ccy = to_px(_CENTER)
    icons.draw_piece(surf, ptype, icons.PLAYER_COLORS[DEMO_COLOR_INDEX],
                     piece_size, (int(ccx), int(ccy)))

    # movegen markers (drawn on top so they read over the gray pieces)
    for mv in moves:
        if mv.to not in window:
            continue
        cx, cy = to_px(mv.to)
        if mv.kind == "shoot":
            rr = s * 0.42
            w = max(2, int(round(s * 0.085)))
            pygame.draw.circle(surf, SHOOT_COLOR, (cx, cy), rr, w)
            pygame.draw.line(surf, SHOOT_COLOR,
                             (cx - rr, cy), (cx + rr, cy), w)
            pygame.draw.line(surf, SHOOT_COLOR,
                             (cx, cy - rr), (cx, cy + rr), w)
        elif mv.kind == "raise":
            rr = s * 0.34
            w = max(3, int(round(s * 0.14)))
            pygame.draw.line(surf, RAISE_COLOR,
                             (cx - rr, cy), (cx + rr, cy), w)
            pygame.draw.line(surf, RAISE_COLOR,
                             (cx, cy - rr), (cx, cy + rr), w)
        elif mv.to in gs.board:
            w = max(2, int(round(s * 0.11)))
            pygame.draw.circle(surf, CAPTURE_COLOR, (cx, cy), s * 0.52, w)
        else:
            pygame.draw.circle(surf, QUIET_COLOR, (cx, cy), s * 0.18)

    _CACHE[key] = surf
    return surf


if __name__ == "__main__":
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    types = [t for t in icons.TYPE_ORDER if t in engine.PIECE_NAMES]
    cols = 5
    rows = (len(types) + cols - 1) // cols
    dw = 240
    dh = max(movement_diagram(t, dw).get_height() for t in types)
    sheet = pygame.Surface((cols * dw, rows * dh))
    sheet.fill((36, 39, 48))
    for i, t in enumerate(types):
        sheet.blit(movement_diagram(t, dw),
                   ((i % cols) * dw, (i // cols) * dh))
    _out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "diagrams_preview.png")
    pygame.image.save(sheet, _out)
    print("saved", _out)
    pygame.quit()
