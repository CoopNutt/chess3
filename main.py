"""Chess 3 — hexagonal battle chess for 2-6 players with 14 new troops.

Host a game, send friends the lobby code, they join from the same app.
"""
import json
import math
import os
import queue
import threading
import time
from pathlib import Path

import pygame

import engine
import icons
import net
import sounds

try:
    import diagrams
except Exception:       # diagrams are optional eye-candy; never block the game
    diagrams = None

SQ3 = math.sqrt(3)

# ---------------------------------------------------------------------------
# Themes — set_theme() rebinds the color globals; everything reads them live.
# ---------------------------------------------------------------------------

THEMES = {
    "Classic": dict(bg=(24, 26, 32), panel=(36, 39, 48),
                    panel_light=(48, 52, 64), accent=(110, 180, 255),
                    cells=[(216, 183, 143), (191, 150, 104), (168, 123, 78)],
                    piece_style=dict(rim=None, glow=None,
                                     ink=(25, 25, 30), glyph=(245, 245, 245))),
    "Midnight": dict(bg=(11, 15, 26), panel=(21, 28, 46),
                     panel_light=(32, 42, 66), accent=(90, 200, 255),
                     cells=[(72, 86, 118), (56, 68, 98), (42, 52, 78)],
                     piece_style=dict(rim=(46, 66, 110), glow=(80, 170, 255),
                                      ink=(16, 22, 40), glyph=(235, 244, 255))),
    "Forest": dict(bg=(14, 22, 16), panel=(24, 36, 28),
                   panel_light=(34, 50, 40), accent=(140, 220, 120),
                   cells=[(152, 182, 122), (120, 152, 94), (90, 122, 72)],
                   piece_style=dict(rim=(36, 66, 44), glow=None,
                                    ink=(18, 32, 22), glyph=(240, 248, 236))),
    "Ember": dict(bg=(26, 16, 14), panel=(42, 26, 22),
                  panel_light=(58, 36, 30), accent=(255, 150, 80),
                  cells=[(226, 170, 120), (198, 134, 88), (160, 100, 64)],
                  piece_style=dict(rim=(84, 38, 24), glow=(255, 120, 40),
                                   ink=(40, 18, 12), glyph=(255, 242, 230))),
    "Ice": dict(bg=(16, 22, 30), panel=(28, 38, 50),
                panel_light=(40, 52, 68), accent=(120, 210, 255),
                cells=[(196, 214, 228), (160, 184, 204), (124, 152, 176)],
                piece_style=dict(rim=(210, 236, 252), glow=(150, 220, 255),
                                 ink=(24, 40, 56), glyph=(248, 252, 255))),
}
THEME_ORDER = list(THEMES)

BG = PANEL = PANEL_LIGHT = ACCENT = None
CELL_SHADES = None
CURRENT_THEME = "Classic"
TEXT = (232, 233, 238)
TEXT_DIM = (150, 155, 168)
GOOD = (120, 220, 130)
BAD = (240, 110, 110)
SEL_COLOR = (255, 240, 120)
LASTMOVE_TINT = (90, 140, 220)
DANGER_TINT = (225, 60, 60)


def set_theme(name):
    global BG, PANEL, PANEL_LIGHT, ACCENT, CELL_SHADES, CURRENT_THEME
    t = THEMES.get(name) or THEMES["Classic"]
    CURRENT_THEME = name if name in THEMES else "Classic"
    BG = t["bg"]
    PANEL = t["panel"]
    PANEL_LIGHT = t["panel_light"]
    ACCENT = t["accent"]
    CELL_SHADES = t["cells"]
    # the theme restyles the pieces too (rim/glow/linework — never the
    # player colors, those are identity)
    if hasattr(icons, "set_style"):
        icons.set_style(**t["piece_style"])
    if diagrams is not None and hasattr(diagrams, "clear_cache"):
        diagrams.clear_cache()


set_theme("Classic")

CFG_PATH = Path.home() / ".chess3.json"

VERSION = "4.1.0"

# Per-troop movement animation profiles.
#   dur: seconds  |  ease: out / in_expo (accelerate) / steps (fast increments)
#   arc: parabolic lift (jump/fly)  |  slam: impact ring+shake+sound at landing
#   fx flags: spin wind, smoke+crack_path, crack_land, phase+lightning,
#             afterimages, alpha (ghost), trail (skeleton), fire_on_capture
ANIM_PROFILES = {
    "K":  dict(dur=0.24, ease="out"),
    "Q":  dict(dur=0.32, ease="steps"),
    "R":  dict(dur=0.15, ease="out"),
    "B":  dict(dur=0.10, ease="out"),
    "N":  dict(dur=0.26, ease="out", arc=0.55),
    "P":  dict(dur=0.45, ease="out"),
    "CN": dict(dur=0.50, ease="out"),
    "AR": dict(dur=0.10, ease="out"),
    "WZ": dict(dur=0.38, phase=True, crack_land=True, snd="lightning"),
    "DR": dict(dur=0.46, ease="out", arc=1.25, slam=True,
               fire_on_capture=True, crack_capture=True),
    "CH": dict(dur=0.11, ease="out", afterimages=True, slam=True, snd="whoosh"),
    "BM": dict(dur=0.24, ease="out"),
    "GH": dict(dur=0.26, ease="out", alpha=110),
    "NE": dict(dur=0.24, ease="out"),
    "CT": dict(dur=0.52, ease="out", arc=1.45, slam=True, crack_land=True),
    "VA": dict(dur=0.30, ease="out", spin=True, snd="whoosh"),
    "GO": dict(dur=0.55, ease="out", snd="grind"),
    "JG": dict(dur=0.42, ease="in_expo", smoke=True, crack_path=True,
               slam=True),
    "SN": dict(dur=0.10, ease="out"),
    "WD": dict(dur=0.24, ease="out"),
    "SK": dict(dur=0.50, ease="out", trail=True),
}

SHAPE_CYCLE = ["hexagon", "square", "triangle", "octagon"]
MOVE_TIMER_OPTS = [0, 15, 30, 60, 120]
TOTAL_TIMER_OPTS = [0, 5, 10, 20, 30]
SWAP_TROOPS = ["CT", "VA", "GO", "JG", "SN", "WD"]
SWAP_SHORT = {"CT": "Catapult", "VA": "Valkyrie", "GO": "Golem",
              "JG": "Jugger", "SN": "Sniper", "WD": "Warden",
              "CN": "Cannon", "AR": "Archer", "WZ": "Wizard", "CH": "Champ",
              "BM": "Bomber", "GH": "Ghost", "NE": "Necro", "DR": "Dragon"}
SWAP_TARGETS = [None, "CN", "AR", "WZ", "CH", "BM", "GH", "NE", "DR"]

_fonts = {}


def font(sz, bold=False):
    key = (sz, bold)
    if key not in _fonts:
        _fonts[key] = pygame.font.SysFont("segoeui,arial", sz, bold=bold)
    return _fonts[key]


def draw_text(surf, s, pos, sz=18, color=TEXT, bold=False, center=False, right=False):
    img = font(sz, bold).render(s, True, color)
    r = img.get_rect()
    if center:
        r.center = pos
    elif right:
        r.topright = pos
    else:
        r.topleft = pos
    surf.blit(img, r)
    return r


def wrap_text(s, sz, width):
    words = s.split()
    lines, cur = [], ""
    f = font(sz)
    for w in words:
        t = (cur + " " + w).strip()
        if f.size(t)[0] <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def load_cfg():
    try:
        return json.loads(CFG_PATH.read_text("utf-8"))
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        CFG_PATH.write_text(json.dumps(cfg), "utf-8")
    except Exception:
        pass


def clipboard_put(text):
    try:
        pygame.scrap.put_text(text)
        return True
    except Exception:
        pass
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False


def clipboard_get():
    try:
        t = pygame.scrap.get_text()
        if t:
            return t
    except Exception:
        pass
    return ""


class Button:
    def __init__(self, label, rect, color=None, enabled=True, sz=20):
        self.label = label
        self.rect = pygame.Rect(rect)
        self.color = color   # None -> the CURRENT theme's accent at draw time
        self.enabled = enabled
        self.sz = sz

    def draw(self, surf, mouse):
        hov = self.rect.collidepoint(mouse) and self.enabled
        base = (self.color or ACCENT) if self.enabled else (70, 74, 84)
        col = tuple(min(255, c + 30) for c in base) if hov else base
        pygame.draw.rect(surf, col, self.rect, border_radius=10)
        pygame.draw.rect(surf, (0, 0, 0), self.rect, 2, border_radius=10)
        if not self.enabled:
            tcol = (120, 124, 134)
        elif sum(col) > 340:            # bright button -> dark label
            tcol = (18, 20, 26)
        else:                           # dark/panel button -> light label
            tcol = TEXT
        draw_text(surf, self.label, self.rect.center, self.sz, tcol, bold=True, center=True)

    def hit(self, pos):
        return self.enabled and self.rect.collidepoint(pos)


class TextInput:
    def __init__(self, rect, text="", placeholder="", max_len=24, upper=False):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.placeholder = placeholder
        self.max_len = max_len
        self.upper = upper
        self.active = False

    def handle(self, ev):
        if ev.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(ev.pos)
        elif ev.type == pygame.KEYDOWN and self.active:
            if ev.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif ev.key == pygame.K_v and (ev.mod & pygame.KMOD_CTRL):
                pasted = clipboard_get()
                for ch in pasted:
                    if ch.isprintable() and len(self.text) < self.max_len:
                        self.text += ch.upper() if self.upper else ch
            elif ev.unicode and ev.unicode.isprintable() and ev.key != pygame.K_RETURN:
                if len(self.text) < self.max_len:
                    self.text += ev.unicode.upper() if self.upper else ev.unicode

    def draw(self, surf):
        pygame.draw.rect(surf, (28, 30, 38), self.rect, border_radius=8)
        border = ACCENT if self.active else (80, 84, 96)
        pygame.draw.rect(surf, border, self.rect, 2, border_radius=8)
        pad = 10
        if self.text:
            draw_text(surf, self.text, (self.rect.x + pad, self.rect.centery - 12), 20)
        else:
            draw_text(surf, self.placeholder, (self.rect.x + pad, self.rect.centery - 12), 20, TEXT_DIM)
        if self.active and (time.time() * 2) % 2 < 1:
            w = font(20).size(self.text)[0]
            x = self.rect.x + pad + w + 2
            pygame.draw.line(surf, TEXT, (x, self.rect.y + 8), (x, self.rect.bottom - 8), 2)


def axial_round(qf, rf):
    sf = -qf - rf
    q, r, s = round(qf), round(rf), round(sf)
    dq, dr, ds = abs(q - qf), abs(r - rf), abs(s - sf)
    if dq > dr and dq > ds:
        q = -r - s
    elif dr > ds:
        r = -q - s
    return (int(q), int(r))


class BoardView:
    """Renders the hex board with the local player's home edge at the bottom."""

    def __init__(self):
        self.state = None
        self.my_pid = 0
        self.shape = "hexagon"
        self.size = 6
        self.s = 24.0
        self.origin = (0, 0)
        self.area = pygame.Rect(0, 0, 100, 100)
        self.selected = None
        self.legal = {}          # to-cell -> Move (preview for ANY piece)
        self.legal_clickable = False   # True only for your piece on your turn
        self.zoom = 1.0
        self.pan = [0.0, 0.0]
        self.anim = None         # dict: type,color,from_px,to_px,t0,dur
        self.beam = None         # dict: from_px,to_px,t0
        self.flashes = []        # (cell, t0)
        self.last_cells = []     # lasting from/to highlight of the last move
        self.hover = None
        self.my_edge_cells = set()
        self.king_danger = False
        self.danger_cells = set()   # capture targets of the current selection
        self.cells = set()
        self.last_deaths = 0        # pieces that died in the latest update
        self.last_kind = None
        self.cracked = set()        # permanently cracked tiles (cosmetic)
        self.particles = []         # transient effect particles
        self.projectile = None      # arrow / cannonball in flight
        self.shake_t0 = 0.0         # board shake on slams/explosions
        self.arrows = []            # [(from_cell, to_cell)] planning arrows
        self.marks = set()          # right-clicked highlight tiles
        self.arrow_anchor = None    # right-drag in progress
        self.protect_cells = set()  # friendlies guarded by the selection
        self._t2d = {}           # true cell -> display cell (orientation)
        self._d2t = {}

    def set_state(self, sd, my_pid):
        now = time.time()
        old = self.state
        self.last_deaths = 0
        self.last_kind = None
        self.state = engine.GameState.from_dict(sd)
        self.shape = getattr(self.state, "shape", "hexagon")
        self.size = self.state.radius
        self.cells = engine.shape_cells(self.shape, self.size)
        self.my_pid = my_pid
        me = next((p for p in self.state.players if p["pid"] == my_pid), None)
        seat = me["seat"] if me else 0
        self._t2d = {c: engine.shape_orient(self.shape, c, seat, self.size)
                     for c in self.cells}
        self._d2t = {d: c for c, d in self._t2d.items()}
        self._compute_edge_cells(me)
        last = sd.get("_last_move")
        if last and last.get("move"):
            self.last_cells = [tuple(last["move"].get("from", (99, 99))),
                               tuple(last["move"].get("to", (99, 99)))]
        if old is not None and last:
            self._animate_diff(old, last, now)
        self.select_cell(None)
        me_alive = bool(me and me["alive"])
        try:
            self.king_danger = (me_alive and self.state.winner is None
                                and self.state.king_in_danger(my_pid))
        except Exception:
            self.king_danger = False
        self._layout()

    def select_cell(self, cell):
        """Select any piece (yours or an enemy's) to preview its moves;
        capture/shoot targets of the SELECTION are the red danger tiles and
        friendly pieces it guards get the theme-colored protection tint."""
        self.selected = None
        self.legal = {}
        self.legal_clickable = False
        self.danger_cells = set()
        self.protect_cells = set()
        if cell is None or self.state is None:
            return
        pc = self.state.board.get(cell)
        if pc is None:
            return
        self.selected = cell
        try:
            self.legal = {mv.to: mv for mv in self.state.legal_moves(cell)}
        except Exception:
            self.legal = {}
        self.legal_clickable = (pc.owner == self.my_pid and self.my_turn())
        gs = self.state
        self.danger_cells = {to for to, mv in self.legal.items()
                             if mv.kind == "shoot"
                             or (mv.kind == "move" and to in gs.board)}
        try:
            self.protect_cells = self._compute_protected(cell, pc)
        except Exception:
            self.protect_cells = set()

    def _compute_protected(self, cell, pc):
        """Friendly-occupied tiles this piece guards: if the piece standing
        there were an enemy, could the selection capture or shoot it?
        (Checked with pseudo moves — a bodyguard doesn't stop guarding just
        because he's pinned.)"""
        gs = self.state
        out = set()
        enemy_pid = next((p["pid"] for p in gs.players
                          if p["pid"] != pc.owner), pc.owner + 1)
        for t, f in list(gs.board.items()):
            if f.owner != pc.owner or t == cell:
                continue
            if engine.hex_dist(cell, t) > 6:
                continue
            saved = gs.board[t]
            gs.board[t] = engine.Piece(f.type, enemy_pid, True)
            try:
                if any(mv.to == t and mv.kind in ("move", "shoot")
                       for mv in gs._pseudo_moves(cell)):
                    out.add(t)
            finally:
                gs.board[t] = saved
        return out

    # ---- planning arrows & marks (right-click, chess.com style) ----

    def begin_arrow(self, pos):
        self.arrow_anchor = self.px_to_cell(pos)

    def end_arrow(self, pos):
        a, self.arrow_anchor = self.arrow_anchor, None
        b = self.px_to_cell(pos)
        if a is None or b is None:
            return
        if a == b:
            self.marks.symmetric_difference_update({a})
        else:
            arrow = (a, b)
            if arrow in self.arrows:
                self.arrows.remove(arrow)
            else:
                self.arrows.append(arrow)

    def clear_annotations(self):
        self.arrows = []
        self.marks = set()
        self.arrow_anchor = None

    def _compute_edge_cells(self, me):
        self.my_edge_cells = set()
        if not me or self.state is None:
            return
        try:
            self.my_edge_cells = set(
                engine.shape_edge_row(self.shape, me["seat"], self.size, 0))
        except Exception:
            pass

    @staticmethod
    def _line_cells(frm, to):
        """Cells strictly between frm and to along a straight hex ray
        (works for ortho rays; empty list otherwise)."""
        dq, dr = to[0] - frm[0], to[1] - frm[1]
        n = engine.hex_dist(frm, to)
        if n <= 1:
            return []
        if dq % n or dr % n:
            return []
        sq, sr = dq // n, dr // n
        return [(frm[0] + sq * i, frm[1] + sr * i) for i in range(1, n)]

    def _spawn(self, kind, cell, **extra):
        p = {"kind": kind, "cell": cell, "t0": time.time()}
        p.update(extra)
        self.particles.append(p)

    def _animate_diff(self, old, last, now):
        mv = last.get("move") or {}
        kind = mv.get("kind")
        frm = tuple(mv.get("from", (0, 0)))
        to = tuple(mv.get("to", (0, 0)))
        pid = last.get("pid", 0)
        color = icons.PLAYER_COLORS[self._color_of(pid)]

        mover = self.state.board.get(to)
        mover_type = mover.type if (kind == "move" and mover) else None
        old_target = old.board.get(to)
        captured = (kind == "move" and old_target is not None
                    and old_target.owner != pid)

        # death bookkeeping (flashes + counters for sounds)
        deaths = 0
        boomed_bombers = []
        for cell, pc in old.board.items():
            if cell != frm and cell not in self.state.board:
                self.flashes.append((cell, now))
                deaths += 1
                if pc.type == "BM":
                    boomed_bombers.append(cell)
        for cell, pc in self.state.board.items():
            oldpc = old.board.get(cell)
            if oldpc is not None and oldpc.owner != pc.owner and cell != to:
                self.flashes.append((cell, now))
                deaths += 1
        # a bomber that vanished at the mover's destination exploded there
        if (kind == "move" and old_target is not None
                and old_target.type == "BM" and to not in boomed_bombers):
            boomed_bombers.append(to)
        # the mover itself may have blown up on arrival (fuse / capture)
        if (kind == "move" and mover is None and frm in old.board
                and old.board[frm].type == "BM"):
            boomed_bombers.append(to)
            mover_type = "BM"
        self.last_deaths = deaths
        self.last_kind = kind

        prof = ANIM_PROFILES.get(mover_type or "", {})
        if kind == "move" and mover_type is not None:
            self.anim = {"type": mover_type, "color": color, "frm": frm,
                         "to": to, "t0": now, "dur": prof.get("dur", 0.2),
                         "prof": prof, "captured": captured}
            # ---- permanent cracks + impact effects per profile ----
            if prof.get("crack_path"):
                for c in self._line_cells(frm, to) + [to]:
                    self.cracked.add(c)
            if prof.get("crack_land"):
                self.cracked.add(to)
            if prof.get("crack_capture") and captured:
                self.cracked.add(to)
            if prof.get("phase"):
                self._spawn("bolt", to, delay=prof["dur"] * 0.55)
            if prof.get("slam"):
                self.shake_t0 = now + prof.get("dur", 0.2)
            if prof.get("fire_on_capture") and captured:
                self._spawn("fire", to, delay=prof.get("dur", 0.3))
            if prof.get("smoke"):
                self._spawn("smoketrail", frm, to=to, dur=prof.get("dur", 0.4))
            if mover_type == "CN" and captured:
                self.projectile = {"kind": "cannonball", "frm": frm, "to": to,
                                   "t0": now, "dur": 0.28}
                self.cracked.add(to)
        elif kind == "shoot":
            shooter = old.board.get(frm) or self.state.board.get(frm)
            arrow_like = shooter is not None and shooter.type in ("AR", "SN")
            self.projectile = {"kind": "arrow" if arrow_like else "cannonball",
                               "frm": frm, "to": to, "t0": now, "dur": 0.15}
            if shooter is not None and shooter.type == "CT":
                self.cracked.add(to)
                self.shake_t0 = now + 0.15
        elif kind == "raise":
            self._spawn("spawnglow", to)
        elif kind == "grave":
            self._spawn("spawnglow", to, dark=True)
        # every bomber explosion permanently cracks its surroundings
        for bc in boomed_bombers:
            self.cracked.add(bc)
            for d in engine.ORTHO:
                self.cracked.add((bc[0] + d[0], bc[1] + d[1]))
            self.shake_t0 = now
        self.cracked &= self.cells

    def _color_of(self, pid):
        for p in (self.state.players if self.state else []):
            if p["pid"] == pid:
                return p.get("color", pid) % len(icons.PLAYER_COLORS)
        return pid % len(icons.PLAYER_COLORS)

    def set_area(self, rect):
        if rect != self.area:
            self.area = pygame.Rect(rect)
            self._layout()

    def _layout(self):
        if self.state is None:
            return
        xs, ys = [], []
        for c in self.cells:
            q, r = self._t2d[c]
            xs.append(SQ3 * (q + r / 2))
            ys.append(1.5 * r)
        w = (max(xs) - min(xs)) + SQ3
        h = (max(ys) - min(ys)) + 2.0
        self.s = min(self.area.w / w, self.area.h / h) * 0.99 * self.zoom
        # keep the pan from flinging the board off-screen
        lim_x = self.area.w * 0.66 * self.zoom
        lim_y = self.area.h * 0.66 * self.zoom
        self.pan[0] = max(-lim_x, min(lim_x, self.pan[0]))
        self.pan[1] = max(-lim_y, min(lim_y, self.pan[1]))
        cx = (max(xs) + min(xs)) / 2
        cy = (max(ys) + min(ys)) / 2
        self.origin = (self.area.centerx - cx * self.s + self.pan[0],
                       self.area.centery - cy * self.s + self.pan[1])

    def zoom_at(self, pos, factor):
        """Zoom toward the cursor, keeping the point under it fixed."""
        if self.state is None:
            return
        old_s = self.s
        wx = (pos[0] - self.origin[0]) / old_s
        wy = (pos[1] - self.origin[1]) / old_s
        self.zoom = max(1.0, min(2.6, self.zoom * factor))
        self._layout()
        self.pan[0] += pos[0] - (self.origin[0] + wx * self.s)
        self.pan[1] += pos[1] - (self.origin[1] + wy * self.s)
        self._layout()

    def pan_by(self, dx, dy):
        self.pan[0] += dx
        self.pan[1] += dy
        self._layout()

    def reset_view(self):
        self.zoom = 1.0
        self.pan = [0.0, 0.0]
        self._layout()

    def cell_to_px(self, cell):
        q, r = self._t2d.get(cell, cell)
        return (self.origin[0] + SQ3 * (q + r / 2) * self.s,
                self.origin[1] + 1.5 * r * self.s)

    def px_to_cell(self, pos):
        x = (pos[0] - self.origin[0]) / self.s
        y = (pos[1] - self.origin[1]) / self.s
        rf = y / 1.5
        qf = x / SQ3 - rf / 2
        return self._d2t.get(axial_round(qf, rf))

    def hex_points(self, center, scale=1.0):
        pts = []
        for k in range(6):
            a = math.radians(60 * k - 30)
            pts.append((center[0] + self.s * scale * math.cos(a),
                        center[1] + self.s * scale * math.sin(a)))
        return pts

    # ---- animation renderers ----

    def _draw_mover(self, surf, now):
        a = self.anim
        prof = a.get("prof", {})
        raw = min(1.0, (now - a["t0"]) / a["dur"])
        ease = prof.get("ease", "out")
        if ease == "in_expo":
            t = raw ** 3
        elif ease == "steps":
            n = max(1, engine.hex_dist(a["frm"], a["to"]))
            seg, frac = divmod(raw * n, 1.0)
            t = min(1.0, (seg + min(1.0, frac * 3)) / n)
        else:
            t = 1 - (1 - raw) ** 2
        fx, fy = self.cell_to_px(a["frm"])
        tx, ty = self.cell_to_px(a["to"])
        x, y = fx + (tx - fx) * t, fy + (ty - fy) * t
        size = int(self.s * 1.15)

        lift = prof.get("arc")
        if lift:
            y -= math.sin(math.pi * raw) * lift * self.s
            size = int(size * (1 + 0.25 * math.sin(math.pi * raw)))

        if prof.get("smoke") and raw < 1:
            self._spawn("smoke", None, px=x, py=y)
        if prof.get("trail") and raw < 1:
            self._spawn("inktrail", None, px=x, py=y)
        if prof.get("afterimages"):
            for back, alp in ((0.35, 70), (0.18, 130)):
                bt = max(0.0, t - back)
                bx, by = fx + (tx - fx) * bt, fy + (ty - fy) * bt
                ghost = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
                icons.draw_piece(ghost, a["type"], a["color"], size, (size, size))
                ghost.set_alpha(alp)
                surf.blit(ghost, (bx - size, by - size))

        alpha = prof.get("alpha")
        if prof.get("phase"):
            # wizard: fade out at origin, vanish, fade in at destination
            if raw < 0.4:
                x, y, alpha = fx, fy, int(255 * (1 - raw / 0.4))
            elif raw < 0.6:
                return
            else:
                x, y, alpha = tx, ty, int(255 * (raw - 0.6) / 0.4)

        if alpha is not None:
            ghost = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
            icons.draw_piece(ghost, a["type"], a["color"], size, (size, size))
            ghost.set_alpha(alpha)
            surf.blit(ghost, (x - size, y - size))
        else:
            icons.draw_piece(surf, a["type"], a["color"], size, (int(x), int(y)))

        if prof.get("spin"):
            # whirling wind arcs around the valkyrie
            for k in range(3):
                ang = now * 9 + k * 2.1
                r = self.s * (0.75 + 0.15 * math.sin(now * 5 + k))
                ax, ay = x + math.cos(ang) * r, y + math.sin(ang) * r * 0.6
                pygame.draw.arc(surf, (225, 235, 245),
                                pygame.Rect(ax - 9, ay - 5, 18, 10),
                                ang, ang + 2.2, 2)

    def _draw_projectile(self, surf, now):
        pr = self.projectile
        if pr is None:
            return
        t = (now - pr["t0"]) / pr["dur"]
        if t >= 1:
            self.projectile = None
            return
        fx, fy = self.cell_to_px(pr["frm"])
        tx, ty = self.cell_to_px(pr["to"])
        x, y = fx + (tx - fx) * t, fy + (ty - fy) * t
        if pr["kind"] == "arrow":
            ang = math.atan2(ty - fy, tx - fx)
            ln = self.s * 0.7
            hx, hy = x + math.cos(ang) * ln / 2, y + math.sin(ang) * ln / 2
            pygame.draw.line(surf, (235, 220, 170),
                             (x - math.cos(ang) * ln / 2,
                              y - math.sin(ang) * ln / 2), (hx, hy), 3)
            side = 0.35 * self.s
            pygame.draw.polygon(surf, (235, 220, 170), [
                (hx + math.cos(ang) * side * 0.6, hy + math.sin(ang) * side * 0.6),
                (hx + math.cos(ang + 2.5) * side * 0.35, hy + math.sin(ang + 2.5) * side * 0.35),
                (hx + math.cos(ang - 2.5) * side * 0.35, hy + math.sin(ang - 2.5) * side * 0.35)])
        else:  # cannonball with a small lob
            y -= math.sin(math.pi * t) * self.s * 0.9
            pygame.draw.circle(surf, (30, 30, 34), (int(x), int(y)),
                               max(3, int(self.s * 0.22)))
            pygame.draw.circle(surf, (90, 90, 100), (int(x), int(y)),
                               max(3, int(self.s * 0.22)), 1)

    def _draw_particles(self, surf, now):
        keep = []
        for p in self.particles:
            age = now - p["t0"] - p.get("delay", 0)
            if age < 0:
                keep.append(p)
                continue
            kind = p["kind"]
            if kind in ("smoke", "inktrail"):
                dur = 0.7
                if age < dur:
                    keep.append(p)
                    k = age / dur
                    r = max(2, int(self.s * (0.18 + 0.25 * k)))
                    col = ((120, 120, 124) if kind == "smoke" else (25, 25, 30))
                    fade = tuple(int(c + (BG[i] - c) * k) for i, c in enumerate(col))
                    pygame.draw.circle(surf, fade,
                                       (int(p["px"]), int(p["py"] - age * 14)), r)
            elif kind == "smoketrail":
                dur = p.get("dur", 0.4)
                if age < dur:
                    keep.append(p)
                    fx, fy = self.cell_to_px(p["cell"])
                    tx, ty = self.cell_to_px(p["to"])
                    k = (age / dur) ** 3
                    self._spawn("smoke", None, px=fx + (tx - fx) * k,
                                py=fy + (ty - fy) * k)
            elif kind == "bolt":
                dur = 0.35
                if age < dur:
                    keep.append(p)
                    cx, cy = self.cell_to_px(p["cell"])
                    top = cy - self.s * 6
                    pts = [(cx, top)]
                    seg = 6
                    rng = (hash(p["cell"]) & 0xffff) or 1
                    for i in range(1, seg):
                        yy = top + (cy - top) * i / seg
                        xx = cx + math.sin(rng * i * 12.9898) * self.s * 0.5
                        pts.append((xx, yy))
                    pts.append((cx, cy))
                    w = 4 if age < 0.12 else 2
                    pygame.draw.lines(surf, (255, 255, 210), False, pts, w)
                    if age < 0.12:
                        pygame.draw.circle(surf, (255, 255, 230),
                                           (int(cx), int(cy)), int(self.s * 0.7), 2)
            elif kind == "fire":
                dur = 0.65
                if age < dur:
                    keep.append(p)
                    cx, cy = self.cell_to_px(p["cell"])
                    rng = abs(hash(p["cell"])) % 997
                    for i in range(14):
                        a = (rng + i * 61) % 360
                        spd = 0.5 + ((rng + i * 7) % 50) / 60
                        d = age * spd * self.s * 2.2
                        px = cx + math.cos(math.radians(a)) * d
                        py = cy + math.sin(math.radians(a)) * d * 0.6 - age * 26
                        k = age / dur
                        col = (255, int(200 * (1 - k)) + 30, 30)
                        pygame.draw.circle(surf, col, (int(px), int(py)),
                                           max(1, int(self.s * 0.16 * (1 - k))))
            elif kind == "spawnglow":
                dur = 0.9
                if age < dur:
                    keep.append(p)
                    cx, cy = self.cell_to_px(p["cell"])
                    k = age / dur
                    col = ((160, 90, 220) if p.get("dark")
                           else (90, 230, 120))
                    for ring in range(3):
                        rk = (k + ring * 0.2) % 1.0
                        pygame.draw.circle(
                            surf, tuple(int(c * (1 - rk)) for c in col),
                            (int(cx), int(cy)),
                            max(2, int(self.s * (0.2 + rk * 0.9))), 2)
        self.particles = keep[-160:]

    # ---- interaction ----

    def my_turn(self):
        gs = self.state
        if gs is None or gs.winner is not None:
            return False
        me = next((p for p in gs.players if p["pid"] == self.my_pid), None)
        return bool(me and me["alive"] and gs.turn_pid == self.my_pid)

    def click(self, pos):
        """Returns a Move to submit, or None."""
        if self.state is None:
            return None
        cell = self.px_to_cell(pos)
        if cell is None:
            self.select_cell(None)
            return None
        if (self.legal_clickable and self.selected is not None
                and cell in self.legal):
            mv = self.legal[cell]
            self.select_cell(None)
            return mv
        # select any piece (yours or enemy) to preview its moves
        self.select_cell(cell)
        return None

    # ---- drawing ----

    def draw(self, surf, now):
        if self.state is None:
            return
        gs = self.state
        mouse = pygame.mouse.get_pos()
        self.hover = self.px_to_cell(mouse)

        # impact shake: brief decaying jitter after slams/explosions
        base_origin = self.origin
        shake_age = now - self.shake_t0
        if 0 <= shake_age < 0.3:
            k = (1 - shake_age / 0.3) * self.s * 0.18
            self.origin = (base_origin[0] + math.sin(now * 71) * k,
                           base_origin[1] + math.cos(now * 63) * k)

        graveyards = getattr(gs, "graveyards", None) or set()
        for cell in self.cells:
            cx, cy = self.cell_to_px(cell)
            if cell in graveyards:
                pts = self.hex_points((cx, cy), 0.985)
                pygame.draw.polygon(surf, (16, 14, 18), pts)
                pygame.draw.polygon(surf, (60, 52, 66), pts, 2)
                if hasattr(icons, "draw_tombstone"):
                    icons.draw_tombstone(surf, (int(cx), int(cy)),
                                         int(self.s * 1.6))
                continue
            shade = CELL_SHADES[(cell[0] - cell[1]) % 3]
            if cell in self.my_edge_cells:
                mycol = icons.PLAYER_COLORS[self._color_of(self.my_pid)]
                shade = tuple(int(s * 0.75 + m * 0.25) for s, m in zip(shade, mycol))
            if cell in self.last_cells:
                shade = tuple(int(s * 0.6 + t * 0.4)
                              for s, t in zip(shade, LASTMOVE_TINT))
            if cell in self.protect_cells:
                shade = tuple(int(s * 0.45 + t * 0.55)
                              for s, t in zip(shade, ACCENT))
            if cell in self.danger_cells:
                shade = tuple(int(s * 0.45 + t * 0.55)
                              for s, t in zip(shade, DANGER_TINT))
            if cell in self.marks:
                shade = tuple(int(s * 0.5 + t * 0.5)
                              for s, t in zip(shade, ACCENT))
            pts = self.hex_points((cx, cy), 0.985)
            pygame.draw.polygon(surf, shade, pts)
            if cell in self.marks:
                pygame.draw.polygon(surf, ACCENT,
                                    self.hex_points((cx, cy), 0.9), 3)
            if cell in self.cracked and hasattr(icons, "draw_cracks"):
                icons.draw_cracks(surf, cell, (int(cx), int(cy)), int(self.s))
            if cell in self.danger_cells:
                pygame.draw.polygon(surf, (255, 90, 90),
                                    self.hex_points((cx, cy), 0.9), 2)

        # selection + hover outlines
        if self.hover is not None:
            pygame.draw.polygon(surf, (255, 255, 255),
                                self.hex_points(self.cell_to_px(self.hover), 0.95), 2)
        if self.selected is not None:
            pygame.draw.polygon(surf, SEL_COLOR,
                                self.hex_points(self.cell_to_px(self.selected), 0.92), 3)

        # legal move markers
        for to, mv in self.legal.items():
            cx, cy = self.cell_to_px(to)
            if mv.kind == "shoot":
                rr = self.s * 0.42
                pygame.draw.circle(surf, BAD, (cx, cy), rr, 3)
                pygame.draw.line(surf, BAD, (cx - rr, cy), (cx + rr, cy), 3)
                pygame.draw.line(surf, BAD, (cx, cy - rr), (cx, cy + rr), 3)
            elif mv.kind == "raise":
                rr = self.s * 0.34
                pygame.draw.line(surf, GOOD, (cx - rr, cy), (cx + rr, cy), 5)
                pygame.draw.line(surf, GOOD, (cx, cy - rr), (cx, cy + rr), 5)
            elif to in gs.board:
                pygame.draw.circle(surf, (235, 90, 90), (cx, cy), self.s * 0.52, 4)
            else:
                pygame.draw.circle(surf, (90, 200, 110), (cx, cy), self.s * 0.18)

        # pieces
        anim_target = None
        if self.anim is not None:
            if (now - self.anim["t0"]) / self.anim["dur"] >= 1:
                self.anim = None
            else:
                anim_target = self.anim["to"]
        for cell, pc in gs.board.items():
            if cell == anim_target:
                continue
            cx, cy = self.cell_to_px(cell)
            col = icons.PLAYER_COLORS[self._color_of(pc.owner)]
            icons.draw_piece(surf, pc.type, col, int(self.s * 1.15), (int(cx), int(cy)))
            if pc.type == "SK":
                # skeleton lifespan pips (3 moves then it crumbles)
                left = max(0, 3 - getattr(pc, "uses", 0))
                for i in range(left):
                    pygame.draw.circle(surf, (140, 240, 150),
                                       (int(cx - self.s * 0.3 + i * self.s * 0.3),
                                        int(cy + self.s * 0.62)), max(2, int(self.s * 0.07)))
        if self.anim is not None:
            self._draw_mover(surf, now)

        self._draw_projectile(surf, now)
        self._draw_particles(surf, now)

        # archer beam
        if self.beam is not None:
            t = (now - self.beam["t0"]) / 0.25
            if t >= 1:
                self.beam = None
            else:
                fx, fy = self.cell_to_px(self.beam["frm"])
                tx, ty = self.cell_to_px(self.beam["to"])
                pygame.draw.line(surf, (255, 230, 120), (fx, fy), (tx, ty), 4)
                pygame.draw.circle(surf, (255, 230, 120), (int(tx), int(ty)), int(self.s * 0.3), 3)

        # death flashes
        keep = []
        for cell, t0 in self.flashes:
            t = (now - t0) / 0.45
            if t < 1:
                keep.append((cell, t0))
                cx, cy = self.cell_to_px(cell)
                alpha_r = self.s * (0.3 + 0.5 * t)
                col = (255, int(180 * (1 - t)) + 60, 60)
                pygame.draw.circle(surf, col, (int(cx), int(cy)), int(alpha_r), 3)
        self.flashes = keep

        # planning arrows on top of everything (semi-transparent theme color)
        pending = ([(self.arrow_anchor, self.px_to_cell(mouse))]
                   if self.arrow_anchor is not None else [])
        if self.arrows or pending:
            ov = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
            acol = (*ACCENT, 185)
            for a, b in self.arrows + pending:
                if a is None or b is None or a == b:
                    continue
                ax, ay = self.cell_to_px(a)
                bx, by = self.cell_to_px(b)
                ang = math.atan2(by - ay, bx - ax)
                head = self.s * 0.62
                ex = bx - math.cos(ang) * head * 0.7
                ey = by - math.sin(ang) * head * 0.7
                pygame.draw.line(ov, acol, (ax, ay), (ex, ey),
                                 max(4, int(self.s * 0.24)))
                pygame.draw.polygon(ov, acol, [
                    (bx, by),
                    (bx - math.cos(ang - 0.5) * head,
                     by - math.sin(ang - 0.5) * head),
                    (bx - math.cos(ang + 0.5) * head,
                     by - math.sin(ang + 0.5) * head)])
            surf.blit(ov, (0, 0))

        # restore un-shaken origin so hit-testing stays stable
        self.origin = base_origin


class App:
    def __init__(self):
        pygame.init()
        try:
            pygame.scrap.init()
        except Exception:
            pass
        self.win = pygame.display.set_mode((1280, 800), pygame.RESIZABLE)
        pygame.display.set_caption("Chess 3")
        try:
            ico = pygame.Surface((32, 32), pygame.SRCALPHA)
            icons.draw_piece(ico, "DR", (214, 74, 74), 30, (16, 16))
            pygame.display.set_icon(ico)
        except Exception:
            pass
        self.clock = pygame.time.Clock()
        self.cfg = load_cfg()
        set_theme(self.cfg.get("theme", "Classic"))
        self.screen = "MENU"
        self.help_open = False
        self.help_scroll = 0
        self.toasts = []
        self.lobby_settings = dict(getattr(net, "DEFAULT_SETTINGS",
                                           {"shape": "hexagon", "move_secs": 0,
                                            "total_mins": 0, "swaps": {}}))
        self.game_clock = None      # last {"move_left","total_left"} payload
        self.game_clock_at = 0.0    # when it arrived (for client-side countdown)
        self.friend_input = TextInput((0, 0, 260, 40), "", "add a friend's name",
                                      max_len=16)
        self._bg_cache = None       # (size, theme) -> hex pattern surface
        self._panning = False
        self.invites = []           # [{"from","code","t0"}] bottom-right toasts
        self._prev_turn_mine = False
        self._prev_log_len = 0
        sounds.init()
        sounds.set_enabled(self.cfg.get("sound_on", True))
        sounds.set_volume(self.cfg.get("volume", 0.7))
        self.presence = None
        try:
            self.presence = net.PresenceService(self.cfg.get("name", "Player"))
            self.presence.start()
        except Exception:
            self.presence = None
        if self.cfg.get("fullscreen"):
            self._apply_fullscreen(True, save=False)
        self.update_info = None       # newer release found on GitHub
        self.update_status = ""       # "" | downloading text
        self.pending_move = None      # awaiting CONFIRM (settings toggle)
        self._check_updates()
        self.server = None
        self.client = None
        self.board = BoardView()
        self.lobby_players = []
        self.port = None
        self.lan_code = ""
        self.pub_code = None
        self.upnp_status = ""
        self.join_status = ""
        self._join_results = queue.Queue()  # (gen, ok, payload) per attempt
        self._join_gen = 0        # invalidates stale/cancelled join attempts
        self._joining = False
        self._upnp_mapped_port = None
        self.winner_info = None
        self.esc_at = 0

        self.name_input = TextInput((0, 0, 300, 44), self.cfg.get("name", ""),
                                    "your name", max_len=16)
        self.code_input = TextInput((0, 0, 340, 48), "", "lobby code or ip:port",
                                    max_len=25, upper=True)

    # ---------- lifecycle ----------

    def toast(self, msg, color=TEXT):
        self.toasts.append([msg, time.time(), color])

    def cleanup_net(self):
        self._join_gen += 1      # invalidate any in-flight join attempt
        self._joining = False
        self.join_status = ""
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
        if self.server:
            srv = self.server
            self.server = None
            # NB: the UPnP mapping is intentionally KEPT until app exit —
            # unmapping here races a re-host's fresh mapping on the same port
            threading.Thread(target=srv.close, daemon=True).start()
        self.lobby_players = []
        self.winner_info = None
        self.board = BoardView()
        if self.presence is not None:
            try:
                self.presence.set_host_code(None)
            except Exception:
                pass

    def _typing(self):
        """True when a text input on the CURRENT screen has focus."""
        if self.screen == "MENU":
            return self.name_input.active
        if self.screen == "JOIN":
            return self.name_input.active or self.code_input.active
        if self.screen == "FRIENDS":
            return self.friend_input.active
        return False

    # ---------- look & feel ----------

    def draw_background(self):
        """Theme background with a subtle hex lattice."""
        W, H = self.win.get_size()
        key = (W, H, CURRENT_THEME)
        if self._bg_cache is None or self._bg_cache[0] != key:
            surf = pygame.Surface((W, H))
            surf.fill(BG)
            line = tuple(min(255, c + 8) for c in BG)
            s = 38
            rows = int(H / (1.5 * s)) + 2
            cols = int(W / (SQ3 * s)) + 2
            for row in range(-1, rows):
                for ci in range(-1, cols):
                    cx = ci * SQ3 * s + (row % 2) * SQ3 * s / 2
                    cy = row * 1.5 * s
                    pts = [(cx + s * 0.96 * math.cos(math.radians(60 * k - 30)),
                            cy + s * 0.96 * math.sin(math.radians(60 * k - 30)))
                           for k in range(6)]
                    pygame.draw.polygon(surf, line, pts, 1)
            self._bg_cache = (key, surf)
        self.win.blit(self._bg_cache[1], (0, 0))

    def panel(self, rect, radius=16):
        """Soft-shadowed themed panel."""
        r = pygame.Rect(rect)
        shadow = r.move(0, 5)
        dark = tuple(max(0, c - 9) for c in BG)
        pygame.draw.rect(self.win, dark, shadow, border_radius=radius)
        pygame.draw.rect(self.win, PANEL, r, border_radius=radius)
        edge = tuple(min(255, c + 16) for c in PANEL)
        pygame.draw.rect(self.win, edge, r, 1, border_radius=radius)
        return r

    def cycle_theme(self):
        i = THEME_ORDER.index(CURRENT_THEME)
        set_theme(THEME_ORDER[(i + 1) % len(THEME_ORDER)])
        self._bg_cache = None
        self.cfg["theme"] = CURRENT_THEME
        save_cfg(self.cfg)

    # ---------- settings ----------

    def _apply_fullscreen(self, on, save=True):
        try:
            if on:
                self.win = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                self.win = pygame.display.set_mode((1280, 800), pygame.RESIZABLE)
        except Exception:
            self.win = pygame.display.set_mode((1280, 800), pygame.RESIZABLE)
            on = False
        self._bg_cache = None
        self.cfg["fullscreen"] = bool(on)
        if save:
            save_cfg(self.cfg)

    def _settings_buttons(self):
        W, H = self.win.get_size()
        cx = W // 2
        fs = self.cfg.get("fullscreen", False)
        snd = self.cfg.get("sound_on", True)
        vol = self.cfg.get("volume", 0.7)
        vol_name = "Low" if vol < 0.45 else ("Medium" if vol < 0.85 else "High")
        confirm = self.cfg.get("confirm_moves", False)
        rows = [
            ("DISPLAY", "Fullscreen" if fs else "Windowed", self._toggle_fullscreen),
            ("SOUND", "On" if snd else "Off", self._toggle_sound),
            ("VOLUME", vol_name, self._cycle_volume),
            ("THEME", CURRENT_THEME, self.cycle_theme),
            ("CONFIRM MOVES", "On" if confirm else "Off",
             self._toggle_confirm_moves),
        ]
        out = []
        y = H // 2 - 120
        for label, value, action in rows:
            out.append((label, Button(value, (cx + 10, y, 190, 44),
                                      color=PANEL_LIGHT, sz=16), action))
            y += 58
        out.append(("", Button("BACK", (cx - 80, y + 24, 160, 46),
                               color=(120, 126, 140)), self._friends_back))
        return out

    def _toggle_fullscreen(self):
        self._apply_fullscreen(not self.cfg.get("fullscreen", False))

    def _toggle_sound(self):
        self.cfg["sound_on"] = not self.cfg.get("sound_on", True)
        sounds.set_enabled(self.cfg["sound_on"])
        save_cfg(self.cfg)
        if self.cfg["sound_on"]:
            sounds.play("turn")

    def _cycle_volume(self):
        cur = self.cfg.get("volume", 0.7)
        nxt = 0.35 if cur >= 0.85 else (0.7 if cur < 0.45 else 1.0)
        self.cfg["volume"] = nxt
        sounds.set_volume(nxt)
        save_cfg(self.cfg)
        sounds.play("turn")

    def _toggle_confirm_moves(self):
        self.cfg["confirm_moves"] = not self.cfg.get("confirm_moves", False)
        save_cfg(self.cfg)

    def draw_settings(self, mouse):
        W, H = self.win.get_size()
        cx = W // 2
        draw_text(self.win, "SETTINGS", (cx, H // 5), 44, TEXT, bold=True,
                  center=True)
        self.panel((cx - 260, H // 2 - 150, 520, 300))
        for label, btn, _ in self._settings_buttons():
            if label:
                draw_text(self.win, label, (cx - 230, btn.rect.y + 12), 16,
                          TEXT, bold=True)
            btn.draw(self.win, mouse)

    # ---------- auto-update ----------

    @staticmethod
    def _ver_tuple(tag):
        try:
            return tuple(int(x) for x in str(tag).lstrip("vV").split("."))
        except Exception:
            return (0,)

    def _check_updates(self):
        """On startup: if GitHub has a newer release, offer to update.
        Only meaningful for the frozen exe (source installs use git)."""
        import sys
        if not getattr(sys, "frozen", False):
            return
        if not hasattr(net, "get_latest_release"):
            return

        def _chk():
            rel = net.get_latest_release()
            if rel and self._ver_tuple(rel["tag"]) > self._ver_tuple(VERSION):
                self.update_info = rel
                sounds.play("invite")
        threading.Thread(target=_chk, daemon=True).start()

    def _update_buttons(self):
        W, H = self.win.get_size()
        cx = W // 2
        return [
            ("yes", Button("UPDATE & RESTART", (cx - 170, H // 2 + 26, 340, 46),
                           color=GOOD, enabled=not self.update_status)),
            ("no", Button("LATER", (cx - 80, H // 2 + 82, 160, 38),
                          color=(120, 126, 140), enabled=not self.update_status)),
        ]

    def draw_update_prompt(self, mouse):
        W, H = self.win.get_size()
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((8, 9, 12, 190))
        self.win.blit(veil, (0, 0))
        cx = W // 2
        self.panel((cx - 240, H // 2 - 120, 480, 250))
        icons.draw_piece(self.win, "DR", (214, 74, 74), 46, (cx, H // 2 - 88))
        draw_text(self.win, "UPDATE AVAILABLE", (cx, H // 2 - 52), 26, TEXT,
                  bold=True, center=True)
        tag = (self.update_info or {}).get("tag", "?")
        draw_text(self.win, "Chess 3 %s is out (you have v%s)" % (tag, VERSION),
                  (cx, H // 2 - 18), 17, TEXT_DIM, center=True)
        if self.update_status:
            draw_text(self.win, self.update_status, (cx, H // 2 + 8), 17,
                      ACCENT, center=True)
        for _key, b in self._update_buttons():
            b.draw(self.win, mouse)

    def handle_update_click(self, pos):
        for key, b in self._update_buttons():
            if b.hit(pos):
                if key == "no":
                    self.update_info = None
                else:
                    self._do_update()
                return True
        return True   # modal: swallow all clicks

    def _do_update(self):
        import subprocess
        import sys
        rel = self.update_info
        if not rel:
            return
        exe = Path(sys.executable)
        new_exe = exe.with_name("Chess3_new.exe")
        self.update_status = "Downloading update..."

        def _dl():
            ok = net.download_file(rel["url"], str(new_exe))
            if not ok:
                self.update_status = ""
                self.update_info = None
                self.toast("Update download failed — try again later", BAD)
                return
            bat = exe.with_name("chess3_update.bat")
            pid = os.getpid()
            bat.write_text(
                "@echo off\r\n"
                ":wait\r\n"
                "tasklist /fi \"PID eq %d\" 2>nul | find \"%d\" >nul && "
                "(timeout /t 1 /nobreak >nul & goto wait)\r\n"
                "move /y \"%s\" \"%s\"\r\n"
                "start \"\" \"%s\"\r\n"
                "del \"%%~f0\"\r\n" % (pid, pid, new_exe, exe, exe),
                encoding="ascii")
            subprocess.Popen(["cmd", "/c", str(bat)],
                             creationflags=0x08000000, cwd=str(exe.parent))
            self.update_status = "Restarting..."
            pygame.event.post(pygame.event.Event(pygame.QUIT))
        threading.Thread(target=_dl, daemon=True).start()

    # ---------- friends & recent players ----------

    def friends(self):
        return self.cfg.setdefault("friends", [])

    def recent_players(self):
        return self.cfg.setdefault("recent_players", [])

    def recent_lobbies(self):
        return self.cfg.setdefault("recent_lobbies", [])

    def record_players(self, players):
        mine = self.my_pid()
        recs = self.recent_players()
        changed = False
        for p in players:
            if p.get("pid") == mine:
                continue
            nm = p.get("name", "")
            if not nm:
                continue
            recs[:] = [r for r in recs if r["name"] != nm]
            recs.insert(0, {"name": nm, "when": time.time()})
            changed = True
        if changed:
            del recs[20:]
            save_cfg(self.cfg)

    def record_lobby(self, code, host_name):
        recs = self.recent_lobbies()
        recs[:] = [r for r in recs if r["code"] != code]
        recs.insert(0, {"code": code, "host": host_name, "when": time.time()})
        del recs[5:]
        save_cfg(self.cfg)

    def toggle_friend(self, name):
        fr = self.friends()
        if name in fr:
            fr.remove(name)
        else:
            fr.append(name)
        save_cfg(self.cfg)

    def my_pid(self):
        if self.server is not None:
            return 0
        if self.client is not None:
            return self.client.pid
        return 0

    # ---------- hosting / joining ----------

    def start_host(self):
        self.save_name()
        srv = None
        for port in range(net.DEFAULT_PORT, net.DEFAULT_PORT + 10):
            try:
                srv = net.HostServer(self.name_input.text.strip() or "Host", port)
                srv.start()
                break
            except OSError:
                srv = None
        if srv is None:
            self.toast("Could not open a port to host on", BAD)
            return
        self.server = srv
        self.port = port
        self.lan_ip = net.get_lan_ip()
        self.lan_code = net.encode_code(self.lan_ip, port)
        self.pub_code = None
        self.upnp_status = "Setting up internet access..."
        self.lobby_players = [{"pid": 0, "name": srv.host_name if hasattr(srv, "host_name") else "You", "color": 0}]

        def _pub():
            ip = net.get_public_ip()
            if ip and self.server is srv:
                self.pub_code = net.encode_code(ip, port)
        def _upnp():
            ok, msg = net.upnp_map_port(port)
            if ok:
                self._upnp_mapped_port = port
            if self.server is srv:
                self.upnp_status = (
                    "Auto port-forward worked — the internet code should work anywhere"
                    if ok else
                    "Auto port-forward failed — for internet friends, port-forward "
                    "TCP %d on your router. Or: everyone installs Radmin VPN and "
                    "friends join by typing  <your Radmin IP>:%d" % (port, port))
        threading.Thread(target=_pub, daemon=True).start()
        threading.Thread(target=_upnp, daemon=True).start()
        if self.presence is not None:
            try:
                self.presence.set_host_code(self.lan_code)
            except Exception:
                pass
        self.screen = "HOST_LOBBY"

    def try_join(self):
        if self._joining:
            self.toast("Already connecting — hang on...")
            return
        self.save_name()
        raw = self.code_input.text.strip()
        if not raw:
            self.toast("Type the lobby code first", BAD)
            return
        try:
            ip, port = net.decode_code(raw)
        except ValueError:
            self.toast("That code doesn't look right", BAD)
            return
        self.join_status = "Connecting..."
        name = self.name_input.text.strip() or "Player"
        self._last_join_code = raw.upper()
        self._joining = True
        self._join_gen += 1
        gen = self._join_gen

        def _go():
            c = net.NetClient()
            try:
                c.connect(ip, port, name)
                self._join_results.put((gen, True, c))
            except Exception as e:
                self._join_results.put((gen, False, str(e)))
        threading.Thread(target=_go, daemon=True).start()

    def save_name(self):
        self.cfg["name"] = self.name_input.text.strip()
        save_cfg(self.cfg)
        if self.presence is not None:
            try:
                self.presence.set_name(self.cfg["name"] or "Player")
            except Exception:
                pass

    # ---------- net event pump ----------

    def poll_net(self):
        while True:  # drain ALL finished join attempts (stale + current)
            try:
                gen, ok, payload = self._join_results.get_nowait()
            except queue.Empty:
                break
            stale = (gen != self._join_gen or self.screen != "JOIN"
                     or self.server is not None)
            if gen == self._join_gen:
                self._joining = False
                self.join_status = ""
            if stale:
                # cancelled/superseded attempt: never hijack the screen,
                # and never leave a ghost player in someone's lobby
                if ok:
                    try:
                        payload.close()
                    except Exception:
                        pass
            elif ok:
                self.client = payload
                self.screen = "CLIENT_LOBBY"
            else:
                self.toast("Couldn't connect: %s" % payload, BAD)

        # invites arrive whatever screen you're on
        if self.presence is not None:
            for _ in range(10):
                try:
                    pev = self.presence.events.get_nowait()
                except queue.Empty:
                    break
                if pev.get("t") == "invite" and pev.get("code"):
                    self.invites = [iv for iv in self.invites
                                    if iv["from"] != pev.get("from")]
                    self.invites.append({"from": pev.get("from", "?"),
                                         "code": pev["code"],
                                         "t0": time.time()})
                    del self.invites[:-3]
                    sounds.play("invite")

        q_ = None
        if self.server is not None:
            q_ = self.server.events
        elif self.client is not None:
            q_ = self.client.events
        if q_ is None:
            return
        for _ in range(50):
            try:
                ev = q_.get_nowait()
            except queue.Empty:
                break
            self.handle_net_event(ev)

    def handle_net_event(self, ev):
        t = ev.get("t")
        if t == "lobby":
            self.lobby_players = ev.get("players", [])
            if ev.get("settings"):
                self.lobby_settings = dict(ev["settings"])
            self.record_players(self.lobby_players)
            if (self.client is not None and self.lobby_players
                    and getattr(self, "_last_join_code", None)):
                self.record_lobby(self._last_join_code,
                                  self.lobby_players[0]["name"])
        elif t == "start":
            sd = ev["state"]
            self.board.set_state(sd, self.my_pid())
            self.board.reset_view()
            self.screen = "GAME"
            self.winner_info = None
            self._set_clock(ev.get("clock"))
            self._prev_turn_mine = (sd.get("turn_pid") == self.my_pid())
            self._prev_log_len = len(sd.get("log", []))
            if self._prev_turn_mine:
                sounds.play("turn")
        elif t == "state":
            sd = ev["state"]
            sd["_last_move"] = ev.get("last_move")
            self.pending_move = None   # the world moved on; re-pick
            self.board.set_state(sd, self.my_pid())
            self._set_clock(ev.get("clock"))
            self._state_sounds(sd, ev.get("last_move"))
        elif t == "gameover":
            self.winner_info = (ev.get("winner"), ev.get("name", ""))
            sounds.play("win" if ev.get("winner") == self.my_pid() else "lose")
        elif t == "error":
            self.toast(ev.get("msg", "error"), BAD)
        elif t == "kicked":
            self.toast("Removed from lobby: %s" % ev.get("reason", ""), BAD)
            self.cleanup_net()
            self.screen = "MENU"
        elif t == "disconnected":
            game_over = (self.screen == "GAME"
                         and (self.winner_info is not None
                              or (self.board.state is not None
                                  and self.board.state.winner is not None)))
            if game_over:
                # game finished normally; host just left first — keep the
                # victory screen up instead of yanking to menu with an error
                if self.client:
                    try:
                        self.client.close()
                    except Exception:
                        pass
                    self.client = None
            else:
                self.toast("Lost connection to the host", BAD)
                self.cleanup_net()
                self.screen = "MENU"

    def _state_sounds(self, sd, last_move):
        """Pick ONE effect for this state update, from the board diff the
        renderer just computed (deaths this update), never from old log
        lines — plus the your-turn chime on turn handoff."""
        deaths = self.board.last_deaths
        kind = self.board.last_kind
        anim = self.board.anim
        prof = (anim or {}).get("prof", {})
        captured = (anim or {}).get("captured", False)
        if sd.get("winner") is None:
            if deaths >= 3:
                sounds.play("boom")     # explosion (or a huge chain trade)
            elif kind == "shoot":
                pr = self.board.projectile or {}
                sounds.play("cannon" if pr.get("kind") == "cannonball"
                            else "shoot")
            elif kind == "raise":
                sounds.play("rattle")   # skeleton claws out of the ground
            elif kind == "grave":
                sounds.play("lose")     # an eerie curse settles
            elif kind == "move":
                if captured and prof.get("fire_on_capture"):
                    sounds.play("fire")
                elif captured and self.board.projectile:
                    sounds.play("cannon")
                elif prof.get("snd"):
                    sounds.play(prof["snd"])
                elif prof.get("slam"):
                    sounds.play("slam")
                elif deaths:
                    sounds.play("capture")
        mine = (sd.get("turn_pid") == self.my_pid()
                and sd.get("winner") is None)
        if mine and not self._prev_turn_mine:
            sounds.play("turn")
        self._prev_turn_mine = mine

    def _set_clock(self, clock):
        self.game_clock = clock
        self.game_clock_at = time.time()

    def clock_left(self, key):
        """Client-side countdown of the last server clock payload."""
        if not self.game_clock or self.game_clock.get(key) is None:
            return None
        return max(0, self.game_clock[key] - int(time.time() - self.game_clock_at))

    def _my_graves_left(self):
        gs = self.board.state
        if gs is None or gs.winner is not None:
            return 0
        me = next((p for p in gs.players if p["pid"] == self.board.my_pid), None)
        if me is None or me["alive"]:
            return 0
        gl = getattr(gs, "graves_left", None) or {}
        return gl.get(self.board.my_pid, 0)

    def _try_place_grave(self, pos):
        """Eliminated players may curse ONE empty tile into a graveyard."""
        if self._my_graves_left() <= 0:
            return False
        gs = self.board.state
        cell = self.board.px_to_cell(pos)
        if (cell is None or cell in gs.board
                or cell in (getattr(gs, "graveyards", None) or set())):
            return False
        payload = [cell[0], cell[1]]
        if self.server is not None:
            self.server.submit_host_grave(payload)
        elif self.client is not None and hasattr(self.client, "send_grave"):
            self.client.send_grave(payload)
        return True

    def submit_move(self, mv):
        md = mv.to_dict()
        if self.server is not None:
            self.server.submit_host_move(md)
        elif self.client is not None:
            self.client.send_move(md)

    # ---------- main loop ----------

    def run(self):
        running = True
        while running:
            now = time.time()
            mouse = pygame.mouse.get_pos()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.VIDEORESIZE:
                    self.win = pygame.display.set_mode((max(960, ev.w), max(640, ev.h)),
                                                       pygame.RESIZABLE)
                elif (ev.type == pygame.KEYDOWN and ev.key == pygame.K_h
                        and not self._typing()):
                    # NB: only swallow H when nobody is typing — lobby codes
                    # can contain the letter H!
                    self.help_open = not self.help_open
                elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                    if self.help_open:
                        self.help_open = False
                    elif self.screen == "GAME":
                        if self.pending_move is not None:
                            self.pending_move = None
                        elif now - self.esc_at < 2.0:
                            self.cleanup_net()
                            self.screen = "MENU"
                        else:
                            self.esc_at = now
                            self.toast("Press ESC again to leave the game")
                    elif self.screen in ("FRIENDS", "SETTINGS"):
                        self.screen = "MENU"
                    elif self.screen in ("HOST_LOBBY", "CLIENT_LOBBY", "JOIN"):
                        self.cleanup_net()
                        self.screen = "MENU"
                elif ev.type == pygame.MOUSEWHEEL:
                    if self.help_open:
                        self.help_scroll = max(0, self.help_scroll - ev.y * 60)
                    elif self.screen == "GAME":
                        self.board.zoom_at(mouse, 1.15 ** ev.y)
                elif (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 2
                        and self.screen == "GAME" and not self.help_open):
                    self._panning = True
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 2:
                    self._panning = False
                elif (ev.type == pygame.MOUSEMOTION and self._panning
                        and self.screen == "GAME"):
                    self.board.pan_by(*ev.rel)
                elif (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3
                        and self.screen == "GAME" and not self.help_open
                        and self.board.area.collidepoint(ev.pos)):
                    self.board.begin_arrow(ev.pos)
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 3:
                    if self.board.arrow_anchor is not None:
                        self.board.end_arrow(ev.pos)
                elif (ev.type == pygame.KEYDOWN and ev.key == pygame.K_r
                        and self.screen == "GAME" and not self._typing()):
                    self.board.reset_view()
                else:
                    self.dispatch_event(ev)

            self.poll_net()

            self.draw_background()
            if self.screen == "MENU":
                self.draw_menu(mouse, now)
            elif self.screen == "HOST_LOBBY":
                self.draw_host_lobby(mouse)
            elif self.screen == "JOIN":
                self.draw_join(mouse)
            elif self.screen == "CLIENT_LOBBY":
                self.draw_client_lobby(mouse)
            elif self.screen == "FRIENDS":
                self.draw_friends(mouse)
            elif self.screen == "SETTINGS":
                self.draw_settings(mouse)
            elif self.screen == "GAME":
                self.draw_game(mouse, now)
            if self.help_open:
                self.draw_help(mouse)
            if self.update_info is not None and self.screen == "MENU":
                self.draw_update_prompt(mouse)
            self.draw_invites(mouse, now)
            self.draw_toasts(now)
            pygame.display.flip()
            self.clock.tick(60)
        self.cleanup_net()
        if self.presence is not None:
            try:
                self.presence.close()
            except Exception:
                pass
        if self._upnp_mapped_port is not None:
            try:
                net.upnp_unmap_port(self._upnp_mapped_port, timeout=2.0)
            except Exception:
                pass
        time.sleep(0.15)
        pygame.quit()

    def dispatch_event(self, ev):
        if (self.update_info is not None and self.screen == "MENU"
                and ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1):
            self.handle_update_click(ev.pos)
            return
        if (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1
                and self.invites and self.handle_invite_click(ev.pos)):
            return
        if self.help_open:
            return
        if self.screen == "SETTINGS":
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for _label, b, action in self._settings_buttons():
                    if b.hit(ev.pos):
                        action()
                        break
            return
        if self.screen == "MENU":
            self.name_input.handle(ev)
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for b in self._menu_buttons():
                    if b.hit(ev.pos):
                        self._menu_action(b.label)
        elif self.screen == "JOIN":
            self.name_input.handle(ev)
            self.code_input.handle(ev)
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_RETURN:
                self.try_join()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for b in self._join_buttons():
                    if b.hit(ev.pos):
                        if b.label == "CONNECT":
                            self.try_join()
                        elif b.label.startswith("Rejoin"):
                            code = b.label.rsplit("(", 1)[1].rstrip(")")
                            self.code_input.text = code
                            self.try_join()
                        else:
                            self.screen = "MENU"
        elif self.screen == "FRIENDS":
            self.friend_input.handle(ev)
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_RETURN:
                self._add_friend()
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for b, action in self._friends_buttons():
                    if b.hit(ev.pos):
                        action()
                        break
        elif self.screen == "HOST_LOBBY":
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for b, action in self._host_lobby_buttons():
                    if b.hit(ev.pos):
                        action()
        elif self.screen == "CLIENT_LOBBY":
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                for b in self._client_lobby_buttons():
                    if b.hit(ev.pos):
                        self.cleanup_net()
                        self.screen = "MENU"
        elif self.screen == "GAME":
            if self.winner_info is not None or (self.board.state and self.board.state.winner is not None):
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    if self._gameover_button().hit(ev.pos):
                        self.cleanup_net()
                        self.screen = "MENU"
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if self._help_btn().hit(ev.pos):
                    self.help_open = True
                    return
                if self.pending_move is not None:
                    for key, b in self._confirm_buttons():
                        if b.hit(ev.pos):
                            if key == "yes":
                                self.submit_move(self.pending_move)
                            self.pending_move = None
                            return
                self.board.clear_annotations()
                # zoomed cells can extend under the HUD panels — only clicks
                # inside the board area may reach the board
                if not self.board.area.collidepoint(ev.pos):
                    return
                if self._try_place_grave(ev.pos):
                    return
                mv = self.board.click(ev.pos)
                if mv is not None:
                    if self.cfg.get("confirm_moves", False):
                        self.pending_move = mv
                        self.board.last_cells = [mv.from_, mv.to]
                    else:
                        self.submit_move(mv)

    # ---------- screens ----------

    MENU_LABELS = ["HOST GAME", "JOIN GAME", "FRIENDS", "HOW TO PLAY",
                   "SETTINGS", "QUIT"]

    def _menu_buttons(self):
        W, H = self.win.get_size()
        cx = W // 2
        out = []
        top = H // 2 - 50
        for i, lb in enumerate(self.MENU_LABELS):
            color = ACCENT if i < 3 else (120, 126, 140)
            out.append(Button(lb, (cx - 150, top + i * 58, 300, 48), color=color))
        out.append(self._theme_button())
        return out

    def _theme_button(self):
        W, _ = self.win.get_size()
        return Button("THEME: %s" % CURRENT_THEME.upper(),
                      (W - 230, 14, 216, 40), color=PANEL_LIGHT, sz=15)

    def _menu_action(self, label):
        if label == "HOST GAME":
            self.start_host()
        elif label == "JOIN GAME":
            self.code_input.text = ""
            self.screen = "JOIN"
        elif label == "FRIENDS":
            self.screen = "FRIENDS"
        elif label == "HOW TO PLAY":
            self.help_open = True
            self.help_scroll = 0
        elif label == "SETTINGS":
            self.screen = "SETTINGS"
        elif label == "QUIT":
            pygame.event.post(pygame.event.Event(pygame.QUIT))
        elif label.startswith("THEME"):
            self.cycle_theme()

    _FLOATERS = ["DR", "GH", "WZ", "N", "BM", "AR", "CH", "Q"]

    def draw_menu(self, mouse, now):
        W, H = self.win.get_size()
        cx = W // 2
        # floating troops drifting behind everything
        for i, tp in enumerate(self._FLOATERS):
            fx = (W * (i + 0.5) / len(self._FLOATERS)
                  + math.sin(now * 0.21 + i * 2.1) * 40)
            fy = H * 0.5 + math.sin(now * 0.13 + i * 1.7) * H * 0.42
            ghost = pygame.Surface((72, 72), pygame.SRCALPHA)
            icons.draw_piece(ghost, tp, PANEL_LIGHT, 58, (36, 36))
            ghost.set_alpha(70)
            self.win.blit(ghost, (fx - 36, fy - 36))

        ty = H // 5
        pts = [(cx + 92 * math.cos(math.radians(60 * k - 30)),
                ty + 92 * math.sin(math.radians(60 * k - 30))) for k in range(6)]
        pygame.draw.polygon(self.win, PANEL_LIGHT, pts)
        pygame.draw.polygon(self.win, ACCENT, pts, 3)
        icons.draw_piece(self.win, "DR", (214, 74, 74), 86, (cx, ty))
        draw_text(self.win, "CHESS 3", (cx, ty + 130), 58, TEXT, bold=True, center=True)
        draw_text(self.win, "battle chess — 2 to 6 players — 11 new troops — 4 maps",
                  (cx, ty + 176), 19, TEXT_DIM, center=True)

        self.name_input.rect.topleft = (cx - 150, H // 2 - 112)
        draw_text(self.win, "NAME", (cx - 150, H // 2 - 136), 15, TEXT_DIM, bold=True)
        self.name_input.draw(self.win)
        for b in self._menu_buttons():
            b.draw(self.win, mouse)
        draw_text(self.win, "press H anytime to see how every troop moves",
                  (cx, H - 26), 15, TEXT_DIM, center=True)

    def _join_buttons(self):
        W, H = self.win.get_size()
        cx = W // 2
        out = [Button("CONNECT", (cx - 150, H // 2 + 60, 300, 50)),
               Button("BACK", (cx - 150, H // 2 + 122, 300, 44), color=(120, 126, 140))]
        for i, rec in enumerate(self.recent_lobbies()[:3]):
            out.append(Button("Rejoin %s  (%s)" % (rec["host"], rec["code"]),
                              (cx - 190, H // 2 + 196 + i * 46, 380, 38),
                              color=PANEL_LIGHT, sz=15))
        return out

    def draw_join(self, mouse):
        W, H = self.win.get_size()
        cx = W // 2
        draw_text(self.win, "JOIN GAME", (cx, H // 6), 44, TEXT, bold=True, center=True)
        draw_text(self.win, "Ask the host for their lobby code", (cx, H // 6 + 46), 19,
                  TEXT_DIM, center=True)
        self.name_input.rect.topleft = (cx - 150, H // 2 - 130)
        draw_text(self.win, "NAME", (cx - 150, H // 2 - 154), 15, TEXT_DIM, bold=True)
        self.name_input.draw(self.win)
        self.code_input.rect.topleft = (cx - 170, H // 2 - 40)
        draw_text(self.win, "LOBBY CODE", (cx - 170, H // 2 - 64), 15, TEXT_DIM, bold=True)
        self.code_input.draw(self.win)
        if self.recent_lobbies():
            draw_text(self.win, "RECENT LOBBIES", (cx, H // 2 + 180), 13,
                      TEXT_DIM, bold=True, center=True)
        for b in self._join_buttons():
            b.draw(self.win, mouse)
        if self.join_status:
            draw_text(self.win, self.join_status, (cx, H // 2 - 76), 18, ACCENT,
                      center=True, right=False)

    # ---------- friends screen ----------

    def _online_names(self):
        if self.presence is None:
            return {}
        try:
            return {p["name"]: p for p in self.presence.peers()}
        except Exception:
            return {}

    def _friends_rows(self):
        """[(name, is_friend, online)] friends first, then other recents/online,
        capped to what fits inside the panel at the current window size."""
        fr = self.friends()
        online = self._online_names()
        recents = [r["name"] for r in self.recent_players()]
        rows = [(n, True, n in online) for n in fr]
        rows += [(n, False, n in online) for n in recents if n not in fr]
        rows += [(n, False, True) for n in online
                 if n not in fr and n not in recents]
        _W, H = self.win.get_size()
        panel_h = H - 260
        fit = max(1, (panel_h - 84 - 12) // 42)
        return rows[:fit]

    def draw_friends(self, mouse):
        W, H = self.win.get_size()
        cx = W // 2
        draw_text(self.win, "FRIENDS", (cx, 60), 44, TEXT, bold=True, center=True)
        draw_text(self.win, "Friends are saved on this PC — everyone you play with shows up here",
                  (cx, 110), 17, TEXT_DIM, center=True)
        p = self.panel((cx - 320, 150, 640, H - 260))
        self.friend_input.rect.topleft = (p.x + 24, p.y + 20)
        self.friend_input.draw(self.win)
        for b, _ in self._friends_buttons():
            b.draw(self.win, mouse)
        y = p.y + 84
        rows = self._friends_rows()
        if not rows:
            draw_text(self.win, "Nobody yet — host a game and send your code!",
                      (cx, y + 30), 18, TEXT_DIM, center=True)
        for name, is_friend, online in rows:
            star = "*" if is_friend else " "
            col = ACCENT if is_friend else TEXT
            draw_text(self.win, "%s  %s" % (star, name), (p.x + 30, y), 21, col,
                      bold=is_friend)
            if online:
                pygame.draw.circle(self.win, GOOD, (p.x + 292, y + 13), 5)
                draw_text(self.win, "online", (p.x + 302, y + 3), 14, GOOD)
            y += 42
        draw_text(self.win,
                  "invites live in the GAME LOBBY — host a game and online "
                  "players get INVITE buttons there",
                  (cx, p.bottom - 26), 14, TEXT_DIM, center=True)

    def _friends_buttons(self):
        W, H = self.win.get_size()
        cx = W // 2
        p = pygame.Rect(cx - 320, 150, 640, H - 260)
        out = [(Button("ADD", (p.x + 296, p.y + 20, 80, 40), sz=16),
                self._add_friend),
               (Button("BACK", (cx - 80, p.bottom + 16, 160, 44),
                       color=(120, 126, 140)), self._friends_back)]
        y = p.y + 84
        for name, is_friend, online in self._friends_rows():
            lbl = "REMOVE" if is_friend else "FRIEND"
            colr = (120, 126, 140) if is_friend else GOOD
            out.append((Button(lbl, (p.right - 120, y - 6, 96, 34),
                               color=colr, sz=13),
                        lambda n=name: self.toggle_friend(n)))
            y += 42
        return out

    def _send_invite(self, name):
        ok = False
        if self.presence is not None:
            try:
                ok = self.presence.invite(name)
            except Exception:
                ok = False
        self.toast("Invite sent to %s" % name if ok
                   else "Couldn't reach %s" % name,
                   GOOD if ok else BAD)

    def _add_friend(self):
        nm = self.friend_input.text.strip()
        if nm:
            if nm not in self.friends():
                self.friends().append(nm)
                save_cfg(self.cfg)
            self.friend_input.text = ""

    def _friends_back(self):
        self.screen = "MENU"

    # ---------- match settings (host controls) ----------

    def _apply_settings(self, partial):
        if self.server is not None:
            try:
                ok, err = self.server.set_settings(partial)
            except Exception as e:
                ok, err = False, str(e)
            if not ok:
                self.toast(err or "Can't change that now", BAD)
                return
        self.lobby_settings.update(partial)

    def _cycle_shape(self):
        cur = self.lobby_settings.get("shape", "hexagon")
        n = max(2, len(self.lobby_players))
        maxp = getattr(engine, "SHAPE_MAX_PLAYERS",
                       {"hexagon": 6, "octagon": 6, "square": 4, "triangle": 3})
        i = SHAPE_CYCLE.index(cur) if cur in SHAPE_CYCLE else 0
        for k in range(1, len(SHAPE_CYCLE) + 1):
            cand = SHAPE_CYCLE[(i + k) % len(SHAPE_CYCLE)]
            if maxp.get(cand, 6) >= n:
                self._apply_settings({"shape": cand})
                return

    def _cycle_opt(self, key, opts):
        cur = self.lobby_settings.get(key, 0)
        i = opts.index(cur) if cur in opts else 0
        self._apply_settings({key: opts[(i + 1) % len(opts)]})

    def _cycle_swap(self, troop):
        swaps = dict(self.lobby_settings.get("swaps", {}))
        cur_target = next((d for d, t in swaps.items() if t == troop), None)
        used = {d for d, t in swaps.items() if t != troop}
        seq = [d for d in SWAP_TARGETS if d is None or d not in used]
        i = seq.index(cur_target) if cur_target in seq else 0
        nxt = seq[(i + 1) % len(seq)]
        if cur_target is not None:
            swaps.pop(cur_target, None)
        if nxt is not None:
            swaps[nxt] = troop
        self._apply_settings({"swaps": swaps})

    @staticmethod
    def _fmt_settings(st):
        shape = getattr(engine, "SHAPE_NAMES", {}).get(
            st.get("shape", "hexagon"), st.get("shape", "hexagon").title())
        bits = [shape]
        if st.get("move_secs"):
            bits.append("%ds/move" % st["move_secs"])
        if st.get("total_mins"):
            bits.append("%dmin game" % st["total_mins"])
        for d, t in (st.get("swaps") or {}).items():
            bits.append("%s swapped for %s" % (engine.PIECE_NAMES.get(t, t),
                                               engine.PIECE_NAMES.get(d, d)))
        return "  •  ".join(bits)

    def _host_lobby_buttons(self):
        W, H = self.win.get_size()
        n = len(self.lobby_players)
        st = self.lobby_settings
        maxp = getattr(engine, "SHAPE_MAX_PLAYERS", {}).get(
            st.get("shape", "hexagon"), 6)
        start = Button("START GAME  (%d/%d)" % (n, maxp),
                       (W - 360, H - 90, 300, 54),
                       color=GOOD, enabled=2 <= n <= maxp)
        back = Button("CANCEL", (60, H - 90, 160, 54), color=(120, 126, 140))
        copy_lan = Button("COPY", (520, 158, 90, 36), sz=15)
        copy_net = Button("COPY", (520, 234, 90, 36), sz=15,
                          enabled=self.pub_code is not None)
        out = [
            (start, self._do_start),
            (back, self._do_cancel_lobby),
            (copy_lan, lambda: self._copy(self.lan_code)),
        ]
        if self.pub_code:
            out.append((copy_net, lambda: self._copy(self.pub_code)))

        sp = self._settings_panel_rect()
        shape_nm = getattr(engine, "SHAPE_NAMES", {}).get(
            st.get("shape", "hexagon"), st.get("shape", "hexagon").title())
        rows_left = [
            ("MAP", shape_nm, self._cycle_shape),
            ("MOVE TIME", ("%ds" % st.get("move_secs", 0))
             if st.get("move_secs") else "Off",
             lambda: self._cycle_opt("move_secs", MOVE_TIMER_OPTS)),
            ("GAME TIME", ("%d min" % st.get("total_mins", 0))
             if st.get("total_mins") else "Off",
             lambda: self._cycle_opt("total_mins", TOTAL_TIMER_OPTS)),
        ]
        y = sp.y + 34
        for label, value, action in rows_left:
            out.append((Button(value, (sp.x + 120, y, 130, 30),
                               color=PANEL_LIGHT, sz=14), action))
            y += 38
        swaps = st.get("swaps") or {}
        for i, troop in enumerate(SWAP_TROOPS):
            target = next((d for d, t in swaps.items() if t == troop), None)
            lbl = "%s: %s" % (SWAP_SHORT.get(troop, troop),
                              SWAP_SHORT.get(target, "off") if target
                              else "off")
            cx_ = sp.x + 258 + (i % 2) * 170
            cy_ = sp.y + 34 + (i // 2) * 38
            out.append((Button(lbl, (cx_, cy_, 160, 30),
                               color=PANEL_LIGHT, sz=12),
                        lambda tr=troop: self._cycle_swap(tr)))
        for name, iy in self._lobby_online_rows():
            out.append((Button("INVITE", (W - 60 - 110, iy - 4, 90, 30),
                               sz=13),
                        lambda nm=name: self._send_invite(nm)))
        return out

    def _lobby_online_rows(self):
        """Online LAN players not already in this lobby -> [(name, draw_y)]."""
        _W, H = self.win.get_size()
        in_lobby = {p["name"] for p in self.lobby_players}
        names = [n for n in self._online_names() if n not in in_lobby]
        base = 188 + max(2, len(self.lobby_players)) * 54 + 40
        out = []
        for i, n in enumerate(names[:4]):
            y = base + 26 + i * 40
            if y > H - 300:
                break
            out.append((n, y))
        return out

    def _settings_panel_rect(self):
        _W, H = self.win.get_size()
        return pygame.Rect(60, 396, 600, min(170, H - 396 - 104))

    def _do_start(self):
        ok, err = self.server.start_game()
        if not ok:
            self.toast(err or "Can't start yet", BAD)

    def _do_cancel_lobby(self):
        self.cleanup_net()
        self.screen = "MENU"

    def _copy(self, code):
        if clipboard_put(code):
            self.toast("Copied: %s" % code, GOOD)
        else:
            self.toast("Couldn't copy — type it out instead", BAD)

    def draw_host_lobby(self, mouse):
        W, H = self.win.get_size()
        draw_text(self.win, "GAME LOBBY", (60, 40), 38, TEXT, bold=True)
        draw_text(self.win, "Send a code to your friends — they hit JOIN GAME and type it in",
                  (60, 90), 18, TEXT_DIM)

        panel = self.panel((60, 128, 570, 252))
        draw_text(self.win, "SAME-WIFI CODE", (84, 142), 14, TEXT_DIM, bold=True)
        draw_text(self.win, self.lan_code or "...", (84, 160), 30, GOOD, bold=True)
        draw_text(self.win, "INTERNET CODE", (84, 218), 14, TEXT_DIM, bold=True)
        draw_text(self.win, self.pub_code or "looking up...", (84, 236), 30,
                  ACCENT if self.pub_code else TEXT_DIM, bold=True)
        y = 288
        for ln in wrap_text(self.upnp_status, 14, panel.w - 48)[:3]:
            draw_text(self.win, ln, (84, y), 14, TEXT_DIM)
            y += 18
        draw_text(self.win, "Direct/VPN join: type  %s:%d"
                  % (getattr(self, "lan_ip", "?"), self.port or 0),
                  (84, panel.bottom - 26), 13, TEXT_DIM)

        # match settings panel
        sp = self._settings_panel_rect()
        self.panel(sp)
        draw_text(self.win, "MATCH SETTINGS  (click to change)", (sp.x + 24, sp.y + 10),
                  14, TEXT_DIM, bold=True)
        y = sp.y + 38
        for label in ("MAP", "MOVE TIME", "GAME TIME"):
            draw_text(self.win, label, (sp.x + 24, y), 15, TEXT, bold=True)
            y += 38

        # players panel
        px = 680
        pw = W - px - 60
        panel2 = self.panel((px, 128, pw, H - 258))
        draw_text(self.win, "PLAYERS  (%d / 6, need at least 2)" % len(self.lobby_players),
                  (px + 24, 144), 14, TEXT_DIM, bold=True)
        friends = self.friends()
        for i, p in enumerate(self.lobby_players):
            y = 188 + i * 54
            col = icons.PLAYER_COLORS[p.get("color", i) % 6]
            pygame.draw.circle(self.win, col, (px + 44, y + 14), 15)
            pygame.draw.circle(self.win, (0, 0, 0), (px + 44, y + 14), 15, 2)
            nm = p["name"] + ("  (you)" if p["pid"] == 0 else "")
            if p["name"] in friends and p["pid"] != 0:
                nm += "  *"
            draw_text(self.win, nm, (px + 72, y), 21)
        if len(self.lobby_players) < 2:
            draw_text(self.win, "waiting for players...",
                      (px + 24, 188 + len(self.lobby_players) * 54 + 6),
                      17, TEXT_DIM)
        online_rows = self._lobby_online_rows()
        if online_rows:
            draw_text(self.win, "ONLINE ON YOUR NETWORK",
                      (px + 24, online_rows[0][1] - 26), 13, TEXT_DIM,
                      bold=True)
            for name, y in online_rows:
                pygame.draw.circle(self.win, GOOD, (px + 36, y + 12), 5)
                draw_text(self.win, name, (px + 50, y), 18)

        for b, _ in self._host_lobby_buttons():
            b.draw(self.win, mouse)
        draw_text(self.win, "press H to show your friends how the new troops move",
                  (W // 2, H - 22), 14, TEXT_DIM, center=True)

    def _client_lobby_buttons(self):
        W, H = self.win.get_size()
        return [Button("LEAVE", (W // 2 - 100, H - 110, 200, 48), color=(120, 126, 140))]

    def draw_client_lobby(self, mouse):
        W, H = self.win.get_size()
        draw_text(self.win, "CONNECTED", (W // 2, H // 6), 40, GOOD, bold=True, center=True)
        draw_text(self.win, "Waiting for the host to start the game...",
                  (W // 2, H // 6 + 50), 20, TEXT_DIM, center=True)
        draw_text(self.win, self._fmt_settings(self.lobby_settings),
                  (W // 2, H // 6 + 80), 16, ACCENT, center=True)
        panel = pygame.Rect(W // 2 - 240, H // 6 + 100, 480, H // 2)
        pygame.draw.rect(self.win, PANEL, panel, border_radius=14)
        draw_text(self.win, "PLAYERS", (panel.x + 24, panel.y + 16), 15, TEXT_DIM, bold=True)
        for i, p in enumerate(self.lobby_players):
            y = panel.y + 60 + i * 56
            col = icons.PLAYER_COLORS[p.get("color", i) % 6]
            pygame.draw.circle(self.win, col, (panel.x + 44, y + 14), 15)
            pygame.draw.circle(self.win, (0, 0, 0), (panel.x + 44, y + 14), 15, 2)
            nm = p["name"] + ("  (you)" if p["pid"] == self.my_pid() else "")
            draw_text(self.win, nm, (panel.x + 72, y), 22)
        for b in self._client_lobby_buttons():
            b.draw(self.win, mouse)

    # ---------- game screen ----------

    def _help_btn(self):
        W, _ = self.win.get_size()
        return Button("?", (W - 54, 12, 40, 40), color=(120, 126, 140), sz=22)

    def _confirm_buttons(self):
        area = self.board.area
        cx = area.centerx
        y = area.bottom - 64
        return [("yes", Button("CONFIRM", (cx - 150, y, 140, 44), color=GOOD)),
                ("no", Button("CANCEL", (cx + 10, y, 140, 44),
                              color=(120, 126, 140)))]

    def _gameover_button(self):
        W, H = self.win.get_size()
        return Button("BACK TO MENU", (W // 2 - 140, H // 2 + 70, 280, 52))

    def draw_game(self, mouse, now):
        W, H = self.win.get_size()
        gs = self.board.state
        if gs is None:
            draw_text(self.win, "Loading...", (W // 2, H // 2), 30, TEXT_DIM, center=True)
            return
        top_h = 64
        bot_h = 40
        side_w = 250
        self.board.set_area(pygame.Rect(10, top_h, W - side_w - 20, H - top_h - bot_h))
        self.board.draw(self.win, now)

        # top strip: players
        pygame.draw.rect(self.win, PANEL, (0, 0, W, top_h))
        x = 16
        for p in gs.players:
            col = icons.PLAYER_COLORS[p.get("color", p["pid"]) % 6]
            alive = p["alive"]
            cur = (gs.turn_pid == p["pid"] and gs.winner is None and alive)
            nm = p["name"] + (" (you)" if p["pid"] == self.board.my_pid else "")
            wname = font(18, cur).size(nm)[0]
            if cur:
                pygame.draw.rect(self.win, PANEL_LIGHT, (x - 8, 8, wname + 46, 48),
                                 border_radius=10)
                pygame.draw.rect(self.win, col, (x - 8, 8, wname + 46, 48), 2,
                                 border_radius=10)
            pygame.draw.circle(self.win, col if alive else (90, 90, 96), (x + 14, 32), 13)
            pygame.draw.circle(self.win, (0, 0, 0), (x + 14, 32), 13, 2)
            tcol = TEXT if alive else (110, 112, 120)
            draw_text(self.win, nm, (x + 34, 22), 18, tcol, bold=cur)
            if not alive:
                pygame.draw.line(self.win, BAD, (x + 4, 42), (x + 24, 22), 3)
            x += wname + 62
        self._help_btn().draw(self.win, mouse)

        # spectator banner for eliminated players
        me = next((p for p in gs.players if p["pid"] == self.board.my_pid), None)
        if me and not me["alive"] and gs.winner is None:
            pulse = 0.6 + 0.4 * math.sin(now * 2)
            col = tuple(int(c * pulse) for c in BAD)
            if self._my_graves_left() > 0:
                draw_text(self.win,
                          "YOU'RE OUT — click any empty tile to CURSE it into a graveyard",
                          ((W - side_w) // 2, top_h + 12), 22, col, bold=True,
                          center=True)
            else:
                draw_text(self.win, "YOU'RE OUT — spectating the battle",
                          ((W - side_w) // 2, top_h + 12), 24, col, bold=True,
                          center=True)

        # turn banner
        if gs.winner is None:
            turn_p = next((p for p in gs.players if p["pid"] == gs.turn_pid), None)
            if turn_p:
                if gs.turn_pid == self.board.my_pid:
                    pulse = 0.5 + 0.5 * math.sin(now * 5)
                    col = tuple(int(c * (0.7 + 0.3 * pulse)) for c in GOOD)
                    draw_text(self.win, "YOUR TURN", (W - side_w - 20, top_h + 12), 26,
                              col, bold=True, right=True)
                else:
                    col = icons.PLAYER_COLORS[turn_p.get("color", 0) % 6]
                    draw_text(self.win, "%s's turn" % turn_p["name"],
                              (W - side_w - 20, top_h + 12), 22, col, bold=True, right=True)

        # king danger
        if self.board.king_danger:
            pulse = 0.5 + 0.5 * math.sin(now * 6)
            col = (int(180 + 60 * pulse), 60, 60)
            pygame.draw.rect(self.win, col, (0, 0, W, H), 6)
            draw_text(self.win, "YOUR KING IS IN DANGER!", (W // 2, H - bot_h - 12), 20,
                      col, bold=True, center=True)

        # pending-move confirmation (settings > CONFIRM MOVES)
        if self.pending_move is not None:
            for _key, b in self._confirm_buttons():
                b.draw(self.win, mouse)

        # move timer (under the turn banner)
        mv_left = self.clock_left("move_left")
        if mv_left is not None and gs.winner is None:
            urgent = mv_left <= 10
            tick_col = BAD if (urgent and (now * 2) % 2 < 1) else TEXT
            draw_text(self.win, "%ds" % mv_left, (W - side_w - 20, top_h + 44),
                      30 if urgent else 24, tick_col, bold=True, right=True)

        # right side panel: clock + log + selected piece info
        sx = W - side_w
        pygame.draw.rect(self.win, PANEL, (sx, top_h, side_w, H - top_h))
        y = top_h + 12
        tot_left = self.clock_left("total_left")
        if tot_left is not None and gs.winner is None:
            tcol = BAD if tot_left <= 60 else TEXT
            draw_text(self.win, "TIME LEFT  %d:%02d" % divmod(tot_left, 60),
                      (sx + 16, y), 16, tcol, bold=True)
            y += 26
        draw_text(self.win, "BATTLE LOG", (sx + 16, y), 14, TEXT_DIM, bold=True)
        y += 26
        for line in gs.log[-12:]:
            for ln in wrap_text(line, 14, side_w - 30)[:2]:
                draw_text(self.win, ln, (sx + 16, y), 14, TEXT)
                y += 18
            y += 4
        sel = self.board.selected
        if sel is not None and sel in gs.board:
            pc = gs.board[sel]
            iy = H - 150
            pygame.draw.rect(self.win, PANEL_LIGHT, (sx + 8, iy, side_w - 16, 140),
                             border_radius=10)
            icons.draw_piece(self.win, pc.type,
                             icons.PLAYER_COLORS[self.board._color_of(pc.owner)],
                             44, (sx + 38, iy + 34))
            draw_text(self.win, engine.PIECE_NAMES.get(pc.type, pc.type),
                      (sx + 68, iy + 16), 20, bold=True)
            desc = engine.PIECE_DESCRIPTIONS.get(pc.type, "")
            yy = iy + 48
            for ln in wrap_text(desc, 14, side_w - 44)[:5]:
                draw_text(self.win, ln, (sx + 20, yy), 14, TEXT_DIM)
                yy += 18

        # game over overlay
        if gs.winner is not None or self.winner_info is not None:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((10, 10, 14, 170))
            self.win.blit(veil, (0, 0))
            wpid = gs.winner if gs.winner is not None else self.winner_info[0]
            if wpid == -1:
                draw_text(self.win, "DRAW", (W // 2, H // 2 - 60), 64, TEXT, bold=True,
                          center=True)
            else:
                wp = next((p for p in gs.players if p["pid"] == wpid), None)
                nm = wp["name"] if wp else "???"
                col = icons.PLAYER_COLORS[wp.get("color", 0) % 6] if wp else TEXT
                draw_text(self.win, "%s WINS!" % nm.upper(), (W // 2, H // 2 - 60), 60,
                          col, bold=True, center=True)
                if wpid == self.board.my_pid:
                    draw_text(self.win, "VICTORY!", (W // 2, H // 2), 30, GOOD,
                              bold=True, center=True)
            self._gameover_button().draw(self.win, mouse)

    # ---------- overlays ----------

    HELP_TYPES = ["K", "Q", "R", "B", "N", "P", "CN", "AR", "WZ", "DR", "CH",
                  "BM", "GH", "NE", "SK", "CT", "VA", "GO", "JG", "SN", "WD"]
    CLASSIC_TYPES = ("K", "Q", "R", "B", "N", "P")
    SWAPPABLE_TYPES = ("CT", "VA", "GO", "JG", "SN", "WD")

    def _help_visible_types(self):
        """In a match: only the troops actually in THIS game (skeletons count
        while a Necromancer lives). Outside: the whole catalog."""
        types = [t for t in self.HELP_TYPES if t in engine.PIECE_NAMES]
        gs = self.board.state
        if self.screen == "GAME" and gs is not None:
            present = {pc.type for pc in gs.board.values()}
            if "NE" in present:
                present.add("SK")
            types = [t for t in types if t in present]
        return types

    def draw_help(self, mouse):
        W, H = self.win.get_size()
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((8, 9, 12, 225))
        self.win.blit(veil, (0, 0))
        draw_text(self.win, "THE TROOPS", (W // 2, 30), 32, TEXT, bold=True, center=True)
        draw_text(self.win, "capture a King to knock that player out — last one standing wins    "
                  "(scroll with the mouse wheel, ESC to close)",
                  (W // 2, 66), 15, TEXT_DIM, center=True)
        types = self._help_visible_types()
        cols = 2 if W < 1750 else 3
        entry_w = (W - 100) // cols
        entry_h = 168
        top = 92
        rows = (len(types) + cols - 1) // cols
        max_scroll = max(0, rows * entry_h - (H - top - 16))
        self.help_scroll = min(self.help_scroll, max_scroll)
        self.win.set_clip(pygame.Rect(0, top, W, H - top))
        for i, tp in enumerate(types):
            ex = 50 + (i % cols) * entry_w
            ey = top + (i // cols) * entry_h - self.help_scroll
            if ey + entry_h < top - 10 or ey > H:
                continue
            dia = None
            if diagrams is not None:
                try:
                    dia = diagrams.movement_diagram(tp, 150)
                except Exception:
                    dia = None
            if dia is not None:
                self.win.blit(dia, (ex, ey + 6))
            else:
                icons.draw_piece(self.win, tp, (76, 118, 224), 56, (ex + 74, ey + 80))
            tx = ex + 164
            nm = engine.PIECE_NAMES.get(tp, tp)
            r = draw_text(self.win, nm, (tx, ey + 8), 20, bold=True)
            if tp in self.SWAPPABLE_TYPES:
                draw_text(self.win, "SWAP-IN", (r.right + 10, ey + 13), 12,
                          ACCENT, bold=True)
            elif tp not in self.CLASSIC_TYPES:
                draw_text(self.win, "NEW", (r.right + 10, ey + 13), 12, GOOD,
                          bold=True)
            yy = ey + 36
            for ln in wrap_text(engine.PIECE_DESCRIPTIONS.get(tp, ""), 15,
                                entry_w - 190)[:5]:
                draw_text(self.win, ln, (tx, yy), 15, TEXT_DIM)
                yy += 19
        self.win.set_clip(None)

    # ---------- Steam-style invite cards (bottom-right) ----------

    INVITE_TTL = 30.0

    def _invite_rects(self, now):
        """[(invite, card_rect, join_rect, x_rect)]. Oldest card keeps the
        bottom slot; NEW invites stack upward so a card never restacks
        under the cursor. Base sits above the screens' bottom buttons."""
        W, H = self.win.get_size()
        out = []
        cards = [iv for iv in self.invites if now - iv["t0"] < self.INVITE_TTL]
        self.invites = cards
        for i, iv in enumerate(cards):
            slide = min(1.0, (now - iv["t0"]) / 0.25)
            w, h = 320, 92
            x = W - int((w + 16) * slide)
            y = H - 130 - h - i * (h + 12)
            card = pygame.Rect(x, y, w, h)
            join = pygame.Rect(x + 16, y + h - 38, 130, 28)
            dismiss = pygame.Rect(x + w - 34, y + 8, 24, 24)
            out.append((iv, card, join, dismiss))
        return out

    def draw_invites(self, mouse, now):
        for iv, card, join, dismiss in self._invite_rects(now):
            shadow = card.move(0, 4)
            pygame.draw.rect(self.win, tuple(max(0, c - 9) for c in BG),
                             shadow, border_radius=12)
            pygame.draw.rect(self.win, PANEL_LIGHT, card, border_radius=12)
            pygame.draw.rect(self.win, ACCENT, card, 2, border_radius=12)
            icons.draw_piece(self.win, "DR", (214, 74, 74), 34,
                             (card.x + 28, card.y + 26))
            draw_text(self.win, iv["from"], (card.x + 52, card.y + 8), 18,
                      TEXT, bold=True)
            draw_text(self.win, "invited you to Chess 3",
                      (card.x + 52, card.y + 30), 14, TEXT_DIM)
            hov = join.collidepoint(mouse)
            pygame.draw.rect(self.win, GOOD if not hov else
                             tuple(min(255, c + 30) for c in GOOD),
                             join, border_radius=8)
            draw_text(self.win, "ACCEPT", join.center, 14, (18, 20, 26),
                      bold=True, center=True)
            draw_text(self.win, "x", dismiss.center, 16, TEXT_DIM, center=True)

    def handle_invite_click(self, pos):
        """Returns True if the click landed on an invite card."""
        now = time.time()
        for iv, card, join, dismiss in self._invite_rects(now):
            if join.collidepoint(pos):
                if self._accept_invite(iv):
                    self.invites.remove(iv)
                return True
            if dismiss.collidepoint(pos):
                self.invites.remove(iv)
                return True
            if card.collidepoint(pos):
                return True
        return False

    def _accept_invite(self, iv):
        """Try to join the inviter's lobby. Returns True when the invite is
        consumed; False keeps the card up (refused / needs confirmation)."""
        if self.screen == "GAME" and self.board.state is not None \
                and self.board.state.winner is None:
            self.toast("Finish or leave this game first — the invite will wait",
                       BAD)
            return False
        if (self.server is not None and len(self.lobby_players) >= 2
                and not iv.get("confirm")):
            iv["confirm"] = True
            self.toast("You're hosting! Click ACCEPT again to abandon your lobby",
                       BAD)
            return False
        self.cleanup_net()
        self.screen = "JOIN"
        self.code_input.text = iv["code"]
        self.try_join()
        return True

    def draw_toasts(self, now):
        W, _ = self.win.get_size()
        keep = []
        y = 8
        for msg, t0, color in self.toasts:
            age = now - t0
            if age < 3.2:
                keep.append([msg, t0, color])
                w = font(17, True).size(msg)[0] + 30
                r = pygame.Rect(W // 2 - w // 2, y, w, 34)
                pygame.draw.rect(self.win, (16, 17, 22), r, border_radius=8)
                pygame.draw.rect(self.win, color, r, 2, border_radius=8)
                draw_text(self.win, msg, r.center, 17, color, bold=True, center=True)
                y += 40
        self.toasts = keep


CRASH_LOG = Path.home() / ".chess3-crash.log"


def _selftest_sniper():
    """Headless in-exe regression test: a sniper kill through the real
    server + full client draw path. Run: CHESS3_SELFTEST=sniper Chess3.exe"""
    import socket

    import net as _net
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    app = App()
    srv = _net.HostServer("selftest", port)
    srv.start()
    puppet = _net.NetClient()
    puppet.connect("127.0.0.1", port, "p2")
    srv.set_settings({"swaps": {"AR": "SN"}})
    ok, err = srv.start_game()
    assert ok, err
    app.server = srv

    def pump_and_draw(frames=6):
        for _ in range(frames):
            try:
                ev = srv.events.get(timeout=0.25)
            except queue.Empty:
                ev = None
            if ev:
                app.handle_net_event(ev)
            app.draw_background()
            if app.board.state is not None:
                app.screen = "GAME"
                app.draw_game((400, 300), time.time())
            pygame.display.flip()

    pump_and_draw(8)
    # craft a guaranteed sniper kill on the live server game
    with srv._lock:
        gs2 = srv._gs
        gs2.board.clear()
        R = gs2.radius
        gs2.board[(-R, 0)] = engine.Piece("K", 0)
        gs2.board[(R, 0)] = engine.Piece("K", 1)
        gs2.board[(0, 0)] = engine.Piece("SN", 0)
        gs2.board[(2, 2)] = engine.Piece("N", 1)   # 2 diag steps away
        gs2.turn_pid = 0
        crafted = gs2.to_dict()
    app.handle_net_event({"t": "state", "state": crafted,
                          "last_move": None, "clock": None})
    pump_and_draw(2)
    app.board.select_cell((0, 0))       # crosshair markers render
    pump_and_draw(2)
    srv.submit_host_move({"from": [0, 0], "to": [2, 2], "kind": "shoot"})
    pump_and_draw(10)                   # beam anim + sounds + state update
    assert (2, 2) not in app.board.state.board, "sniper kill not applied"
    print("SELFTEST OK — sniper kill executed and rendered")
    puppet.close()
    srv.close()
    pygame.quit()


def main():
    if os.environ.get("CHESS3_SELFTEST") == "sniper":
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        _selftest_sniper()
        return
    try:
        App().run()
    except Exception:
        # windowed exe has no console: leave a breadcrumb for bug reports
        import traceback
        try:
            with open(CRASH_LOG, "a", encoding="utf-8") as f:
                f.write("\n=== crash %s ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                traceback.print_exc(file=f)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
