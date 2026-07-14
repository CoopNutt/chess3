"""Chess 3 game engine: hex-cell multiplayer chess for 2-6 players.

Pure, headless, deterministic game logic. NO pygame imports here.

Axial coordinates (q, r), pointy-top cells, implicit third coord s = -q - r.
Important hex rule: diagonal movement is never blocked by the two cells it
passes between -- a diagonal ray is blocked only by pieces sitting ON cells
of the ray itself.

v2: cells are ALWAYS axial hex cells, but the board OUTLINE varies
("hexagon" | "square" | "triangle" | "octagon"); see the shape_* functions.

v5: Move gained an optional `arg` (morph target); MOVE_KINDS gained "swap"
(thief exchange) and "morph" (shaman transformation); GameState gained
`mimic_type`, the type the Mimic currently moves and threatens as.
"""

from collections import deque
from functools import lru_cache

# ---------------------------------------------------------------------------
# Hex geometry
# ---------------------------------------------------------------------------

ORTHO = [(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)]
DIAG = [(2, -1), (1, 1), (-1, 2), (-2, 1), (-1, -1), (1, -2)]
KNIGHT = [(3, -1), (3, -2), (2, 1), (1, 2), (-1, 3), (-2, 3),
          (-3, 1), (-3, 2), (-2, -1), (-1, -2), (1, -3), (2, -3)]

# Forward direction pair (F1, F2) for pawns owned by a player seated on edge i.
EDGE_FORWARD = [
    ((0, -1), (1, -1)),   # edge 0: r = R
    ((0, -1), (-1, 0)),   # edge 1: q + r = R
    ((-1, 0), (-1, 1)),   # edge 2: q = R
    ((0, 1), (-1, 1)),    # edge 3: r = -R
    ((0, 1), (1, 0)),     # edge 4: q + r = -R
    ((1, 0), (1, -1)),    # edge 5: q = -R
]

SEAT_EDGES = {2: [0, 3], 3: [0, 2, 4], 4: [0, 1, 3, 4],
              5: [0, 1, 2, 3, 4], 6: [0, 1, 2, 3, 4, 5]}
# Tuned (with the army layout below) so every start position is QUIET:
# no player has any capture, shoot, or instant promotion available on ply 1
# and armies never collide. See tests/test_engine.py::TestQuietStart.
# v2 note: 4-6 players grew from radius 11 to 13 because a swapped-in
# Valkyrie (knight jumps = hex distance 3) in a row-end slot reached the
# adjacent army at 11, and 12 breaks the DEFAULT army by parity.
# v3 note: 13 -> 15, because a swapped-in Juggernaut (5-step ortho charge)
# in a row-end slot reached a neighboring army's pawns at 13-14.
BOARD_RADIUS = {2: 6, 3: 7, 4: 15, 5: 15, 6: 15}


def hex_dist(a, b):
    """Hex distance between two axial cells."""
    dq = a[0] - b[0]
    dr = a[1] - b[1]
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


def rotate60(cell, times=1):
    """Rotate an axial cell by 60 degrees around the origin, `times` times.

    One step maps (q, r) -> (-r, q+r) and maps edge i onto edge (i-1) mod 6.
    """
    q, r = cell
    for _ in range(times % 6):
        q, r = -r, q + r
    return (q, r)


def board_cells(radius):
    """Set of all axial cells (q, r) with max(|q|, |r|, |q+r|) <= radius."""
    return {(q, r)
            for q in range(-radius, radius + 1)
            for r in range(-radius, radius + 1)
            if max(abs(q), abs(r), abs(q + r)) <= radius}


def edge_row(edge_idx, radius, row):
    """Cells of the row at distance `row` from edge `edge_idx`.

    Row 0 is the edge itself.  Cells are ordered consistently along the edge
    (the same rotational order for every edge).
    """
    base = [(q, radius - row) for q in range(-radius, row + 1)]  # edge 0
    k = (6 - edge_idx) % 6  # rotate edge 0 onto edge_idx
    return [rotate60(c, k) for c in base]


def _on_edge_line(cell, edge_idx, radius):
    """True if `cell` lies on the boundary line of the given edge."""
    q, r = cell
    if edge_idx == 0:
        return r == radius
    if edge_idx == 1:
        return q + r == radius
    if edge_idx == 2:
        return q == radius
    if edge_idx == 3:
        return r == -radius
    if edge_idx == 4:
        return q + r == -radius
    return q == -radius


# ---------------------------------------------------------------------------
# Board shapes (v2)
#
# Only the outline varies; the cells themselves stay axial hex cells.
# "square" is an SxS rhombus of hex cells (0<=q<S, 0<=r<S), "triangle" the
# wedge q>=0, r>=0, q+r<=T, "octagon" a hexagon with its 6 corners trimmed.
# ---------------------------------------------------------------------------

SHAPE_NAMES = {"hexagon": "Hexagon", "square": "Square",
               "triangle": "Triangle", "octagon": "Octagon"}
SHAPE_MAX_PLAYERS = {"hexagon": 6, "octagon": 6, "square": 4, "triangle": 3}
OCTAGON_TRIM = 3

# Board size per (shape, player count), found by scripts/search_layouts.py:
# at these sizes every start position is QUIET (zero placement displacements
# and no capture / shoot / instant promotion available to anyone on ply 1)
# for the DEFAULT army and for every single swap troop in SWAP_TROOPS in
# every swappable slot.  Re-run the search before changing sizes, layouts
# or shifts.  v5 note: the expanded matrix (9 troops x 12 slots, incl. the
# newly swappable R/N/B/Q) re-searched to the SAME sizes — TF never
# captures, SH is a 1-stepper and MI starts as a pawn-mimic, so v3's
# 5-tile Juggernaut charge remains the binding stressor.
SHAPE_SIZE = {
    "hexagon": dict(BOARD_RADIUS),
    "square": {2: 12, 3: 22, 4: 22},
    "triangle": {2: 21, 3: 22},
    "octagon": {2: 12, 3: 12, 4: 14, 5: 14, 6: 14},
}

_SHAPE_SEATS = {
    "hexagon": SEAT_EDGES,
    "octagon": SEAT_EDGES,
    "square": {2: [0, 2], 3: [0, 1, 2], 4: [0, 1, 2, 3]},
    "triangle": {2: [0, 1], 3: [0, 1, 2]},
}

_SQUARE_FORWARD = [
    ((0, -1), (1, -1)),   # edge 0: r = S-1   (both decrease r)
    ((-1, 0), (-1, 1)),   # edge 1: q = S-1   (both decrease q)
    ((0, 1), (-1, 1)),    # edge 2: r = 0     (both increase r)
    ((1, 0), (1, -1)),    # edge 3: q = 0     (both increase q)
]
_TRIANGLE_FORWARD = [
    ((0, 1), (-1, 1)),    # edge 0: r = 0     (both increase r)
    ((0, -1), (-1, 0)),   # edge 1: q + r = T (both decrease q+r)
    ((1, 0), (1, -1)),    # edge 2: q = 0     (both increase q)
]

_HEX_CORNERS = ((1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1))


@lru_cache(maxsize=None)
def _shape_cells_frozen(shape, size):
    if shape == "square":
        return frozenset((q, r) for q in range(size) for r in range(size))
    if shape == "triangle":
        return frozenset((q, r) for q in range(size + 1)
                         for r in range(size + 1 - q))
    cells = board_cells(size)
    if shape == "octagon":
        corners = [(cq * size, cr * size) for cq, cr in _HEX_CORNERS]
        cells = {c for c in cells
                 if all(hex_dist(c, k) >= OCTAGON_TRIM for k in corners)}
    return frozenset(cells)


def shape_cells(shape, size):
    """All cells of the `shape` board outline at the given size."""
    return set(_shape_cells_frozen(shape, size))


def shape_num_edges(shape):
    """How many player edges the outline has (6 / 4 / 3)."""
    if shape == "square":
        return 4
    if shape == "triangle":
        return 3
    return 6


def shape_seat_edges(shape, n):
    """The edge indices assigned to `n` players; raises ValueError."""
    seats = _SHAPE_SEATS[shape].get(n)
    if seats is None:
        raise ValueError("unsupported player count for %s: %d" % (shape, n))
    return list(seats)


def shape_edge_forward(shape, edge):
    """The pawn forward direction pair (F1, F2) for a seat on `edge`."""
    if shape == "square":
        return _SQUARE_FORWARD[edge]
    if shape == "triangle":
        return _TRIANGLE_FORWARD[edge]
    return EDGE_FORWARD[edge]


def shape_edge_row(shape, edge, size, row):
    """Ordered cells at distance `row` from `edge` (row 0 = on the edge).

    Only cells inside shape_cells are returned; the ordering is consistent
    along each edge (mirrored handedness so facing armies line up).
    """
    if shape == "square":
        s = size
        if edge == 0:
            return [(q, s - 1 - row) for q in range(s)]
        if edge == 1:
            return [(s - 1 - row, r) for r in range(s - 1, -1, -1)]
        if edge == 2:
            return [(q, row) for q in range(s - 1, -1, -1)]
        return [(row, r) for r in range(s)]
    if shape == "triangle":
        t = size
        if edge == 0:
            return [(q, row) for q in range(t - row + 1)]
        if edge == 1:
            return [(q, t - row - q) for q in range(t - row + 1)]
        return [(row, r) for r in range(t - row + 1)]
    cells = edge_row(edge, size, row)
    if shape == "octagon":
        member = _shape_cells_frozen("octagon", size)
        cells = [c for c in cells if c in member]
    return cells


def shape_on_edge_line(shape, cell, edge, size):
    """True if `cell` lies on the boundary line of the given edge."""
    q, r = cell
    if shape == "square":
        return (r == size - 1, q == size - 1, r == 0, q == 0)[edge]
    if shape == "triangle":
        return (r == 0, q + r == size, q == 0)[edge]
    return _on_edge_line(cell, edge, size)


def shape_edge_dist(shape, cell, edge, size):
    """Distance (in rows) from `cell` to the boundary line of `edge`."""
    q, r = cell
    if shape == "square":
        return (size - 1 - r, size - 1 - q, r, q)[edge]
    if shape == "triangle":
        return (r, size - (q + r), q)[edge]
    return (size - r, size - (q + r), size - q,
            size + r, size + (q + r), size + q)[edge]


def shape_orient(shape, cell, seat, size):
    """DISPLAY transform putting `seat`'s home edge at the canonical spot.

    The engine never uses this; the renderer does.  Triangle boards are not
    rotated (the UI highlights the home edge instead).
    """
    if shape == "square":
        q, r = cell
        if seat == 1:
            return (r, q)
        if seat == 2:
            return (size - 1 - q, size - 1 - r)
        if seat == 3:
            return (size - 1 - r, size - 1 - q)
        return (q, r)
    if shape == "triangle":
        return cell
    return rotate60(cell, seat)


def shape_promotes(shape, seat_edge, cell, size):
    """True if a pawn seated on `seat_edge` promotes upon reaching `cell`.

    hexagon/octagon: boundary cell on the line of an edge at circular
    edge-index distance >= 2 from the seat (a neighboring army's back rank
    never promotes).  square: the OPPOSITE edge only.  triangle: boundary
    cell not on the own edge line, at least (2*T)//3 rows out.
    """
    if shape == "square":
        return shape_on_edge_line("square", cell, (seat_edge + 2) % 4, size)
    if shape == "triangle":
        if shape_on_edge_line("triangle", cell, seat_edge, size):
            return False
        if not any(shape_on_edge_line("triangle", cell, e, size)
                   for e in range(3)):
            return False
        return (shape_edge_dist("triangle", cell, seat_edge, size)
                >= (2 * size) // 3)
    q, r = cell
    if max(abs(q), abs(r), abs(q + r)) != size:
        return False
    if shape == "octagon" and cell not in _shape_cells_frozen("octagon", size):
        return False
    for edge in range(6):
        if _on_edge_line(cell, edge, size):
            d = abs(edge - seat_edge)
            if min(d, 6 - d) >= 2:
                return True
    return False


# ---------------------------------------------------------------------------
# Piece data
# ---------------------------------------------------------------------------

PIECE_NAMES = {
    "K": "King", "Q": "Queen", "R": "Rook", "B": "Bishop", "N": "Knight",
    "P": "Pawn", "CN": "Cannon", "AR": "Archer", "WZ": "Wizard",
    "DR": "Dragon", "CH": "Champion", "BM": "Bomber", "GH": "Ghost",
    "NE": "Necromancer", "CT": "Catapult", "VA": "Valkyrie", "GO": "Golem",
    "JG": "Juggernaut", "SN": "Sniper", "WD": "Warden", "SK": "Skeleton",
    "TF": "Thief", "SH": "Shaman", "MI": "Mimic",
}

PIECE_DESCRIPTIONS = {
    "K": "One step to any of the 6 touching tiles. If he goes down, you're out — guard him with your life.",
    "Q": "Slides as far as she wants, straight or diagonal. Your biggest threat on the board.",
    "R": "Slides any distance in a straight line. An absolute menace on open lanes.",
    "B": "Slides any distance diagonally — and diagonals slip BETWEEN tiles, so nobody can body-block it.",
    "N": "Leaps straight to any of 12 faraway tiles. Whatever's in the way doesn't matter.",
    "P": "Marches forward (double-step on its first move), kills on its forward diagonals, and turns into a QUEEN on a far edge.",
    "CN": "Rolls straight onto empty tiles only. To kill, it hops exactly one piece and smashes the next one behind it.",
    "AR": "Steps one tile at a time, but snipes enemies exactly 2 tiles away in a straight line — without moving, right over blockers. Golems don't care.",
    "WZ": "Blinks to any tile within 2. Walls? Pieces? A teleport doesn't ask.",
    "DR": "Flies up to 3 tiles in any direction, straight or diagonal. Short range, huge coverage.",
    "CH": "Hops 1 or 2 tiles straight, or 1 diagonal — leaping clean over anything in between.",
    "BM": "Trundles up to 2 tiles straight. The moment it kills or dies, it BLOWS UP and wipes every neighbour — only Kings and Golems walk away. Oh, and the fuse is lit: its 10th move sets it off no matter what.",
    "GH": "Drifts up to 3 diagonal tiles, phasing straight THROUGH other pieces. Walls mean nothing to the dead.",
    "NE": "Creeps 1 diagonal tile — or spends one of your dead pawns to raise a SKELETON on a tile beside him. Graveyard tiles work too.",
    "CT": "Crawls one tile, but lobs a shot exactly 3 tiles down a straight line — sailing over everyone's heads. Can't dent a Golem.",
    "VA": "Swoops like a Knight or steps 1 diagonal. Two attack patterns, one piece, zero blockers.",
    "GO": "Stomps 1 tile straight. Arrows bounce off, catapult shots too, explosions just tickle — only a real capture puts it down.",
    "JG": "Charges up to 5 tiles down a straight lane with zero brakes — it either smashes the first enemy in its path or skids to a stop right before whatever blocks it. No parking halfway.",
    "SN": "Sidles 1 diagonal tile, but headshots enemies exactly 2 diagonal tiles out — without moving, straight over anyone's head. Golems just shrug it off.",
    "WD": "Walks 1 tile any direction, like a King. Friends standing right beside it (straight-adjacent) can't be taken by normal moves — though shots and explosions still get through, and nobody guards the guard itself.",
    "SK": "A pawn back from the dead — shuffles forward, stabs on the forward diagonals, and strolls right over graveyard tiles. The glue only holds for 3 moves, then it crumbles. Never promotes.",
    "TF": "Slides straight like a Rook but never hurts anyone. Instead it SWAPS places with the first piece within 3 straight tiles — friend or enemy, your pick. Kings are off-limits, and nobody ever fears a Thief.",
    "SH": "Steps 1 tile straight or diagonal — any way except dead sideways. Every kill feeds it a SOUL; spend souls to permanently morph into almost any other piece. Pawns are free, a Queen runs you 5.",
    "MI": "A perfect copycat: it moves exactly like the LAST piece anyone moved. Rook slid? It's a rook now. Archer sniped? It snipes. New personality every single turn.",
}

# "grave" never comes out of movegen — it is the wire/UI pseudo-kind for a
# dead player cursing a tile (see apply_grave); Move.from_dict accepts it.
# v5 adds "swap" (thief exchange) and "morph" (shaman transformation).
MOVE_KINDS = ("move", "shoot", "raise", "swap", "morph", "grave")

# Swappable troops (v2 added CT/VA/GO, v3 JG/SN/WD, v5 TF/SH/MI): `swaps`
# maps a DEFAULT troop type to its replacement, e.g. {"CN": "CT", "R": "TF"};
# each replacement may be used at most once.  v5: the classic R/N/B/Q became
# swappable too — swapping one replaces ALL pieces of that type in every
# army (both rooks / both knights).  "P" and "K" stay unswappable.
# v5.1: Thief and Mimic joined the base army, so they left the swap pool
# and became swappable slots themselves.
SWAP_TROOPS = ("CT", "VA", "GO", "JG", "SN", "WD", "SH")
SWAPPABLE_TYPES = ("CN", "AR", "WZ", "DR", "CH", "BM", "GH", "NE",
                   "R", "N", "B", "Q", "TF", "MI")

# v5: max ortho steps between a Thief and its swap partner.
THIEF_RANGE = 3

# v5: soul price a Shaman pays to permanently become each type.  "K" and
# "SH" are never morphable (absent on purpose).  Movegen emits one morph
# move per affordable type; the leftover souls stay in Piece.uses.
MORPH_COSTS = {
    "P": 0, "SK": 0,
    "N": 2, "R": 2, "B": 2, "CN": 2, "AR": 2, "SN": 2, "TF": 2,
    "CH": 3, "VA": 3, "GH": 3, "NE": 3, "GO": 3, "CT": 3, "BM": 3, "MI": 3,
    "JG": 4, "DR": 4, "WZ": 4,
    "Q": 5, "WD": 5,
}

# Home rows of an army, nearest the edge first (24 pieces total).
# The pawns form a STAGGERED double shield (rows 2+3): hex diagonals hop
# two rows per step, so a single pawn row cannot block enemy sliders — two
# staggered rows cover both parities. This exact arrangement (with
# _ROW_SHIFTS and BOARD_RADIUS) was searched so that every start position
# is quiet; do not reorder casually — TestQuietStart will catch regressions.
_ARMY_ROWS = (
    # v5.1: the Thief takes the left rook's place, the Mimic the right
    # knight's — one newcomer on each side of the King.
    ("DR", "N", "TF", "K", "Q", "R", "MI"),
    ("BM", "NE", "GH", "B", "CN", "CH", "AR", "WZ"),
    ("P",) * 4,
    ("P",) * 5,
)
_ROW_SHIFTS = (0, 1, 0, 0)
# Per-shape row shift overrides (searched together with SHAPE_SIZE by
# scripts/search_layouts.py; hexagon keeps the v1 machine-tuned shifts).
_SHAPE_ROW_SHIFTS = {
    "hexagon": (0, 1, 0, 0),
    "octagon": (0, 0, 0, 0),
    "square": (0, 0, 0, 1),
    "triangle": (0, 0, 0, 0),
}
ARMY_SIZE = sum(1 for row in _ARMY_ROWS for t in row if t is not None)


def _swapped_army(swaps):
    """A copy of _ARMY_ROWS with `swaps` applied; raises ValueError."""
    if not swaps:
        return _ARMY_ROWS
    used = set()
    for slot, rep in swaps.items():
        if slot not in SWAPPABLE_TYPES:
            raise ValueError("troop %r cannot be swapped out" % (slot,))
        if rep not in SWAP_TROOPS:
            raise ValueError("bad replacement troop %r" % (rep,))
        if rep in used:
            raise ValueError("replacement %r used more than once" % (rep,))
        used.add(rep)
    return tuple(tuple(swaps.get(t, t) for t in row) for row in _ARMY_ROWS)

GHOST_RANGE = 3
JUGGERNAUT_RANGE = 5

_KING_OFFSETS = tuple(ORTHO) + tuple(DIAG)
_CH_OFFSETS = (tuple(ORTHO)
               + tuple((2 * q, 2 * r) for q, r in ORTHO)
               + tuple(DIAG))
_VA_OFFSETS = tuple(KNIGHT) + tuple(DIAG)
_WZ_OFFSETS = tuple(sorted(
    (dq, dr)
    for dq in range(-2, 3) for dr in range(-2, 3)
    if 1 <= (abs(dq) + abs(dr) + abs(dq + dr)) // 2 <= 2))
# v5 Shaman: the 4 ortho dirs excluding the two horizontal "sides"
# (1,0)/(-1,0).  The set is symmetric under negation, which the reverse
# attack test in _cell_attacked relies on.
# v5.1 buff: the 4 non-sideways ortho steps PLUS the necromancer's 6
# diagonal steps (10 directions total, all range 1).
_SH_DIRS = ((0, 1), (-1, 1), (0, -1), (1, -1)) + tuple(DIAG)
_SH_DIR_SET = frozenset(_SH_DIRS)


class Piece:
    """A piece on the board; `owner` is a player id (int).

    `uses` counts COMPLETED moves for pieces that care (v4): a Skeleton
    crumbles after its 3rd move, a Bomber's fuse detonates it on its 10th.
    """

    __slots__ = ("type", "owner", "moved", "uses")

    def __init__(self, type, owner, moved=False, uses=0):
        self.type = type
        self.owner = owner
        self.moved = moved
        self.uses = uses

    def __repr__(self):
        return "Piece(%r, %r, moved=%r, uses=%r)" % (
            self.type, self.owner, self.moved, self.uses)


class Move:
    """A move order with value semantics; kind is one of MOVE_KINDS.

    Movegen only ever produces "move" / "shoot" / "raise" / "swap" /
    "morph"; "grave" exists so the dead-player tile-curse can ride the
    same wire format (net/UI).  `arg` (v5, string|None) carries the morph
    target type; it serializes only when set.
    """

    __slots__ = ("from_", "to", "kind", "arg")

    def __init__(self, from_, to, kind="move", arg=None):
        self.from_ = (int(from_[0]), int(from_[1]))
        self.to = (int(to[0]), int(to[1]))
        self.kind = kind
        self.arg = arg

    def to_dict(self):
        """JSON-safe dict form: {"from":[q,r], "to":[q,r], "kind":...};
        includes "arg" ONLY when it is set."""
        d = {"from": [self.from_[0], self.from_[1]],
             "to": [self.to[0], self.to[1]],
             "kind": self.kind}
        if self.arg is not None:
            d["arg"] = self.arg
        return d

    @staticmethod
    def from_dict(d):
        """Build a Move from its dict form; raises ValueError if malformed.

        Accepts both pre-v5 dicts (no "arg" key) and v5 ones.
        """
        if not isinstance(d, dict):
            raise ValueError("move must be a dict")
        kind = d.get("kind", "move")
        if kind not in MOVE_KINDS:
            raise ValueError("bad move kind: %r" % (kind,))
        arg = d.get("arg")
        if arg is not None and not isinstance(arg, str):
            raise ValueError("bad move arg: %r" % (arg,))
        cells = []
        for key in ("from", "to"):
            v = d.get(key)
            if (not isinstance(v, (list, tuple)) or len(v) != 2 or
                    not all(isinstance(x, int) and not isinstance(x, bool)
                            for x in v)):
                raise ValueError("bad move field %r: %r" % (key, v))
            cells.append((v[0], v[1]))
        return Move(cells[0], cells[1], kind, arg)

    def __eq__(self, other):
        return (isinstance(other, Move) and self.from_ == other.from_
                and self.to == other.to and self.kind == other.kind
                and self.arg == other.arg)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.from_, self.to, self.kind, self.arg))

    def __repr__(self):
        if self.arg is None:
            return "Move(%r, %r, %r)" % (self.from_, self.to, self.kind)
        return "Move(%r, %r, %r, %r)" % (self.from_, self.to, self.kind,
                                         self.arg)


# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------

class GameState:
    """Complete game state.  Mutate only through apply_move / eliminate."""

    def __init__(self, radius, shape="hexagon"):
        self.radius = radius   # board size (hexagon radius / square side / ...)
        self.shape = shape
        self.board = {}        # (q, r) -> Piece
        self.players = []      # {"pid","name","seat","alive","color"}
        self.turn_pid = 0
        self.lost = {}         # pid -> [type, ...] pieces that pid has LOST
        self.winner = None     # None=ongoing, pid=winner, -1=draw
        self.log = []          # human-readable event lines (last 200)
        self.graveyards = set()   # cursed cells (see apply_grave)
        self.graves_left = {}     # pid -> curses remaining (granted on death)
        self.mimic_type = "P"     # v5: what Mimics move as (last acted type)
        self._cells = _shape_cells_frozen(shape, radius)
        self._boom = deque()       # pending explosion centers
        self._dead_kings = []      # owners whose king died this resolution
        self.displacements = 0     # army placement collisions (should be 0)

    # -- construction -------------------------------------------------------

    @staticmethod
    def new_game(players, radius=None, shape="hexagon", swaps=None):
        """Start a game from [(pid, name), ...].

        `shape` picks the board outline; `radius` overrides the searched
        SHAPE_SIZE for that (shape, count); `swaps` optionally replaces
        default troops with SWAP_TROOPS members (see _swapped_army).
        """
        n = len(players)
        if shape not in SHAPE_NAMES:
            raise ValueError("unknown shape: %r" % (shape,))
        if n not in _SHAPE_SEATS[shape]:
            raise ValueError("unsupported player count for %s: %d"
                             % (shape, n))
        army = _swapped_army(swaps)
        size = SHAPE_SIZE[shape][n] if radius is None else radius
        gs = GameState(size, shape)
        seats = shape_seat_edges(shape, n)
        for i, (pid, name) in enumerate(players):
            gs.players.append({"pid": pid, "name": name, "seat": seats[i],
                               "alive": True, "color": i})
            gs.lost[pid] = []
        for i, (pid, _name) in enumerate(players):
            gs._place_army(pid, seats[i], army)
        gs.turn_pid = players[0][0]
        gs._log("Game started with %d players." % n)
        return gs

    def _place_army(self, pid, seat, army=_ARMY_ROWS):
        """Place one army centered within rows 0..3 of `seat`.

        SHAPE_SIZE is tuned so armies never collide (see the quiet-start
        test); `displacements` stays 0 there. The fallback keeps any shifted
        piece within rows 0..4 of its OWN edge so it can never be dumped
        into a neighboring army or onto a promotion cell.
        """
        shifts = _SHAPE_ROW_SHIFTS.get(self.shape, _ROW_SHIFTS)
        planned = []
        for row_i, types in enumerate(army):
            cells = shape_edge_row(self.shape, seat, self.radius, row_i)
            start = (len(cells) - len(types)) // 2 + shifts[row_i]
            start = max(0, min(start, len(cells) - len(types)))
            for t, c in zip(types, cells[start:start + len(types)]):
                if t is not None:
                    planned.append((t, c))
        planned_cells = {c for _t, c in planned}
        home = [c for row_i in range(5)
                for c in shape_edge_row(self.shape, seat, self.radius, row_i)]
        for t, c in planned:
            if c not in self.board:
                self.board[c] = Piece(t, pid)
            else:
                self.displacements += 1
                free = [cell for cell in home
                        if cell not in self.board
                        and cell not in planned_cells]
                if not free:
                    free = [cell for cell in self._cells
                            if cell not in self.board
                            and cell not in planned_cells]
                alt = min(free, key=lambda cell: (hex_dist(cell, c), cell))
                self.board[alt] = Piece(t, pid)

    # -- small helpers ------------------------------------------------------

    def _player(self, pid):
        for p in self.players:
            if p["pid"] == pid:
                return p
        return None

    def _name(self, pid):
        p = self._player(pid)
        return p["name"] if p else ("pid%s" % pid)

    def _is_alive(self, pid):
        p = self._player(pid)
        return bool(p and p["alive"])

    def _seat(self, pid):
        return self._player(pid)["seat"]

    def _log(self, msg):
        self.log.append(msg)
        if len(self.log) > 200:
            del self.log[:len(self.log) - 200]

    def _promotes(self, cell, pid):
        """True if a pawn of `pid` standing on `cell` must promote.

        Delegates to shape_promotes: a far boundary cell (hexagon/octagon),
        the opposite edge (square), or the far tip region (triangle).
        """
        return shape_promotes(self.shape, self._seat(pid), cell, self.radius)

    # -- move generation ----------------------------------------------------

    def _protected(self, cell, owner):
        """True if a Warden owned by `owner` stands ORTHO-adjacent to `cell`.

        The Warden aura: same-owner pieces on its 6 ortho-adjacent cells
        cannot be captured by kind="move" moves.  Consulted by EVERY
        move-capture generator (shoots, explosions and eliminations bypass
        it; wardens never protect themselves, but two wardens CAN protect
        each other).  Hot path: only the 6 neighbors of the target cell
        are scanned — never the whole board.
        """
        q, r = cell
        board = self.board
        for dq, dr in ORTHO:
            pc = board.get((q + dq, r + dr))
            if pc is not None and pc.type == "WD" and pc.owner == owner:
                return True
        return False

    def _pseudo_moves(self, cell):
        """Movement-rule moves for the piece on `cell`, WITHOUT the
        king-safety filter. This is what attack computations use (a pinned
        piece still threatens, exactly like classic chess)."""
        if self.winner is not None:
            return []
        pc = self.board.get(cell)
        if pc is None or not self._is_alive(pc.owner):
            return []
        return self._GEN[pc.type](self, cell, pc)

    def legal_moves(self, cell):
        """All legal moves for the piece on `cell`.

        Returns [] if there is no piece, its owner is dead, or the game is
        over.  Does not depend on whose turn it is (apply_move checks that).
        You may never play a move that leaves YOUR OWN king capturable.
        """
        pc = self.board.get(cell)
        moves = self._pseudo_moves(cell)
        if not moves:
            return moves
        return [m for m in moves if not self._exposes_king(pc.owner, m)]

    def all_legal_moves(self, pid):
        """Every legal move available to player `pid` right now."""
        moves = []
        if self.winner is not None or not self._is_alive(pid):
            return moves
        for cell, pc in list(self.board.items()):
            if pc.owner == pid:
                moves.extend(self.legal_moves(cell))
        return moves

    # -- king-safety simulation ----------------------------------------------

    def _sim_explosion(self, center, removed):
        """Explosion at `center` on the scratch board: record removals in
        `removed` and chain into other bombers. Kings and Golems survive."""
        queue = deque([center])
        while queue:
            cq, cr = queue.popleft()
            for dq, dr in ORTHO:
                t = (cq + dq, cr + dr)
                occ = self.board.get(t)
                if occ is None or occ.type in ("K", "GO"):
                    continue
                removed[t] = self.board.pop(t)
                if occ.type == "BM":
                    queue.append(t)

    def _exposes_king(self, pid, move):
        """Would playing `move` leave pid's king attackable? Simulates the
        move's direct effects (including bomber explosions) on the live board
        dict and restores it exactly afterwards."""
        removed = {}
        added = []
        board = self.board
        try:
            if move.kind == "shoot":
                victim = board.get(move.to)
                if victim is not None:
                    removed[move.to] = board.pop(move.to)
                    if victim.type == "BM":
                        self._sim_explosion(move.to, removed)
            elif move.kind == "raise":
                board[move.to] = Piece("SK", pid, True)
                added.append(move.to)
            elif move.kind == "swap":
                # v5: simulate BOTH pieces exchanging — a swap can pull
                # your own blocker off a line (or hand an enemy slider a
                # cell it attacks your king from).
                a = board.pop(move.from_)
                b = board.pop(move.to)
                removed[move.from_] = a
                removed[move.to] = b
                board[move.from_] = b
                board[move.to] = a
                added.extend((move.from_, move.to))
            elif move.kind == "morph":
                # v5: nothing changes positionally — a morph is exposed
                # iff the king is attacked right now (it never resolves
                # a check).
                pass
            else:  # "move"
                mover = board.get(move.from_)
                if mover is None:
                    return False
                victim = board.get(move.to)
                removed[move.from_] = board.pop(move.from_)
                if victim is not None:
                    removed[move.to] = victim
                board[move.to] = mover
                added.append(move.to)
                explode_here = []
                if victim is not None and victim.type == "BM":
                    explode_here.append(move.to)
                # a bomber that captures — or completes its 10th move —
                # detonates and dies on arrival
                if mover.type == "BM" and (victim is not None
                                           or getattr(mover, "uses", 0) >= 9):
                    del board[move.to]
                    added.remove(move.to)
                    explode_here.append(move.to)
                for c in explode_here:
                    self._sim_explosion(c, removed)
            return self.king_in_danger(pid)
        finally:
            for c in added:
                board.pop(c, None)
            board.update(removed)

    def _slide(self, cell, owner, dirs, max_steps=None, capture=True):
        """Slide moves along `dirs`, stopping at the first occupied cell.

        Diagonal rays are only ever blocked by pieces ON the ray cells, so
        walking the ray cells implements the hex diagonal rule directly.
        Graveyard cells are impassable walls: the ray stops BEFORE them.
        """
        moves = []
        limit = max_steps if max_steps is not None else 4 * self.radius
        for dq, dr in dirs:
            q, r = cell
            for _ in range(limit):
                q += dq
                r += dr
                if (q, r) not in self._cells or (q, r) in self.graveyards:
                    break
                occ = self.board.get((q, r))
                if occ is None:
                    moves.append(Move(cell, (q, r)))
                    continue
                if (capture and occ.owner != owner
                        and not self._protected((q, r), occ.owner)):
                    moves.append(Move(cell, (q, r)))
                break
        return moves

    def _jumps(self, cell, owner, offsets):
        """Jump moves (ignore blockers) to empty or enemy cells.

        Graveyard cells are never valid landing spots (v4).
        """
        moves = []
        for dq, dr in offsets:
            t = (cell[0] + dq, cell[1] + dr)
            if t not in self._cells or t in self.graveyards:
                continue
            occ = self.board.get(t)
            if occ is None or (occ.owner != owner
                               and not self._protected(t, occ.owner)):
                moves.append(Move(cell, t))
        return moves

    def _moves_K(self, cell, pc):
        # kings only step to the 6 touching tiles (no diagonal hops)
        return self._jumps(cell, pc.owner, tuple(ORTHO))

    def _moves_Q(self, cell, pc):
        return self._slide(cell, pc.owner, _KING_OFFSETS)

    def _moves_R(self, cell, pc):
        return self._slide(cell, pc.owner, ORTHO)

    def _moves_B(self, cell, pc):
        return self._slide(cell, pc.owner, DIAG)

    def _moves_N(self, cell, pc):
        return self._jumps(cell, pc.owner, KNIGHT)

    def _moves_P(self, cell, pc):
        # Graveyards block pawns like walls: no stepping on one, and a
        # double-step may not pass over one either.
        f1, f2 = shape_edge_forward(self.shape, self._seat(pc.owner))
        q, r = cell
        moves = []
        for fdq, fdr in (f1, f2):
            one = (q + fdq, r + fdr)
            if (one in self._cells and one not in self.board
                    and one not in self.graveyards):
                moves.append(Move(cell, one))
                if not pc.moved:
                    two = (q + 2 * fdq, r + 2 * fdr)
                    if (two in self._cells and two not in self.board
                            and two not in self.graveyards):
                        moves.append(Move(cell, two))
        # Captures ONLY on the 3 forward diagonals (never blocked).
        for ddq, ddr in ((f1[0] + f2[0], f1[1] + f2[1]),
                         (2 * f1[0] - f2[0], 2 * f1[1] - f2[1]),
                         (2 * f2[0] - f1[0], 2 * f2[1] - f1[1])):
            t = (q + ddq, r + ddr)
            occ = self.board.get(t)
            if (t in self._cells and t not in self.graveyards
                    and occ is not None and occ.owner != pc.owner
                    and not self._protected(t, occ.owner)):
                moves.append(Move(cell, t))
        return moves

    def _moves_SK(self, cell, pc):
        # Skeleton (v4): pawn-style movement for its owner's seat — one
        # forward step (F1/F2) to an empty cell, captures ONLY on the 3
        # forward diagonals — but NO double-step and it NEVER promotes.
        # Uniquely, skeletons may enter graveyard cells.  (Its 3-move
        # crumble lives in apply_move.)
        f1, f2 = shape_edge_forward(self.shape, self._seat(pc.owner))
        q, r = cell
        moves = []
        for fdq, fdr in (f1, f2):
            one = (q + fdq, r + fdr)
            if one in self._cells and one not in self.board:
                moves.append(Move(cell, one))
        for ddq, ddr in ((f1[0] + f2[0], f1[1] + f2[1]),
                         (2 * f1[0] - f2[0], 2 * f1[1] - f2[1]),
                         (2 * f2[0] - f1[0], 2 * f2[1] - f1[1])):
            t = (q + ddq, r + ddr)
            occ = self.board.get(t)
            if (t in self._cells and occ is not None
                    and occ.owner != pc.owner
                    and not self._protected(t, occ.owner)):
                moves.append(Move(cell, t))
        return moves

    def _moves_CN(self, cell, pc):
        # Quiet slides to empty cells only (cannot capture by sliding).
        moves = self._slide(cell, pc.owner, ORTHO, capture=False)
        # Screen jump: exactly one intervening piece, then the FIRST piece
        # beyond it; capture it if it is an enemy.  A graveyard cell walls
        # off the ray (and can never be landed on anyway).
        for dq, dr in ORTHO:
            q, r = cell
            seen_screen = False
            while True:
                q += dq
                r += dr
                if (q, r) not in self._cells or (q, r) in self.graveyards:
                    break
                occ = self.board.get((q, r))
                if occ is None:
                    continue
                if not seen_screen:
                    seen_screen = True
                    continue
                if (occ.owner != pc.owner
                        and not self._protected((q, r), occ.owner)):
                    moves.append(Move(cell, (q, r)))
                break
        return moves

    def _moves_AR(self, cell, pc):
        # 1 ortho step to EMPTY cells only; never captures by moving.
        moves = self._slide(cell, pc.owner, ORTHO, max_steps=1, capture=False)
        # Shoot: enemy at exactly 2 cells along an ortho dir; blockers on the
        # intermediate cell are irrelevant; the archer does not move.
        # Golems are immune to every kind of shoot.
        for dq, dr in ORTHO:
            t = (cell[0] + 2 * dq, cell[1] + 2 * dr)
            occ = self.board.get(t)
            if occ is not None and occ.owner != pc.owner and occ.type != "GO":
                moves.append(Move(cell, t, "shoot"))
        return moves

    def _moves_WZ(self, cell, pc):
        return self._jumps(cell, pc.owner, _WZ_OFFSETS)

    def _moves_DR(self, cell, pc):
        return self._slide(cell, pc.owner, _KING_OFFSETS, max_steps=3)

    def _moves_CH(self, cell, pc):
        return self._jumps(cell, pc.owner, _CH_OFFSETS)

    def _moves_BM(self, cell, pc):
        return self._slide(cell, pc.owner, ORTHO, max_steps=2)

    def _moves_GH(self, cell, pc):
        # Up to GHOST_RANGE diagonal steps, passing THROUGH occupied cells;
        # may land on any empty or enemy cell along the ray (not friendly).
        # Ghosts phase THROUGH graveyard cells but may not land on them.
        moves = []
        for dq, dr in DIAG:
            q, r = cell
            for _ in range(GHOST_RANGE):
                q += dq
                r += dr
                if (q, r) not in self._cells:
                    break
                if (q, r) in self.graveyards:
                    continue
                occ = self.board.get((q, r))
                if occ is None or (occ.owner != pc.owner
                                   and not self._protected((q, r), occ.owner)):
                    moves.append(Move(cell, (q, r)))
        return moves

    def _moves_NE(self, cell, pc):
        moves = self._jumps(cell, pc.owner, DIAG)
        # Raise (v4: spawns a Skeleton): any EMPTY ortho-adjacent cell —
        # graveyard cells included; skeletons rise from graves just fine.
        if "P" in self.lost.get(pc.owner, ()):
            for dq, dr in ORTHO:
                t = (cell[0] + dq, cell[1] + dr)
                if t in self._cells and t not in self.board:
                    moves.append(Move(cell, t, "raise"))
        return moves

    def _moves_CT(self, cell, pc):
        # Catapult: 1 ortho step to EMPTY cells only.  Shoot: destroys an
        # enemy at EXACTLY 3 cells along an ortho ray, ignoring blockers,
        # without moving.  Golems cannot be targeted.
        moves = self._slide(cell, pc.owner, ORTHO, max_steps=1, capture=False)
        for dq, dr in ORTHO:
            t = (cell[0] + 3 * dq, cell[1] + 3 * dr)
            occ = self.board.get(t)
            if occ is not None and occ.owner != pc.owner and occ.type != "GO":
                moves.append(Move(cell, t, "shoot"))
        return moves

    def _moves_VA(self, cell, pc):
        # Valkyrie: jumps (ignoring blockers) to knight offsets or 1 diag.
        return self._jumps(cell, pc.owner, _VA_OFFSETS)

    def _moves_GO(self, cell, pc):
        # Golem: 1 ortho step, move or capture.  (Its shoot/explosion
        # immunities live in the shooters' movegen and _resolve_explosions.)
        return self._jumps(cell, pc.owner, ORTHO)

    def _moves_JG(self, cell, pc):
        # Juggernaut: charges along each ortho ray, max JUGGERNAUT_RANGE
        # steps.  Destinations are ONLY ray endpoints: the first enemy
        # within range (capture) or the last EMPTY cell before a blocker /
        # board edge / the step cap.  No stopping midway on empty cells.
        # A warden-protected enemy acts like a blocker: the charge stops
        # on the cell before it.  So does a graveyard cell (impassable).
        moves = []
        owner = pc.owner
        for dq, dr in ORTHO:
            q, r = cell
            last_empty = None
            hit_cell = None
            hit = None
            for _ in range(JUGGERNAUT_RANGE):
                q += dq
                r += dr
                if (q, r) not in self._cells or (q, r) in self.graveyards:
                    break
                occ = self.board.get((q, r))
                if occ is None:
                    last_empty = (q, r)
                    continue
                hit = occ
                hit_cell = (q, r)
                break
            if (hit is not None and hit.owner != owner
                    and not self._protected(hit_cell, hit.owner)):
                moves.append(Move(cell, hit_cell))
            elif last_empty is not None:
                moves.append(Move(cell, last_empty))
        return moves

    def _moves_SN(self, cell, pc):
        # Sniper: 1 diag step to EMPTY cells only (never captures by
        # moving).  Shoot: kills an enemy at EXACTLY 2 diag steps along one
        # diag direction, ignoring blockers, without moving.  Golems are
        # immune to every kind of shoot; shoots bypass the warden aura.
        moves = self._slide(cell, pc.owner, DIAG, max_steps=1, capture=False)
        for dq, dr in DIAG:
            t = (cell[0] + 2 * dq, cell[1] + 2 * dr)
            occ = self.board.get(t)
            if occ is not None and occ.owner != pc.owner and occ.type != "GO":
                moves.append(Move(cell, t, "shoot"))
        return moves

    def _moves_WD(self, cell, pc):
        # Warden: 1 step in any of the 12 directions, like a King.  (Its
        # protection aura lives in _protected, consulted by every
        # move-capture generator.)
        return self._jumps(cell, pc.owner, _KING_OFFSETS)

    def _moves_TF(self, cell, pc):
        # Thief (v5): slides along ortho rays like a rook but can NEVER
        # capture.  Instead, kind="swap": along each ray, if the FIRST
        # piece within THIEF_RANGE steps (empties between) is anything but
        # a King — either side's — the thief may exchange cells with it.
        # Swaps are not captures: warden auras ignore them, nothing dies,
        # no souls are gained.  Graveyard cells wall the ray off as usual.
        moves = self._slide(cell, pc.owner, ORTHO, capture=False)
        for dq, dr in ORTHO:
            q, r = cell
            for _ in range(THIEF_RANGE):
                q += dq
                r += dr
                if (q, r) not in self._cells or (q, r) in self.graveyards:
                    break
                occ = self.board.get((q, r))
                if occ is None:
                    continue
                if occ.type != "K":
                    moves.append(Move(cell, (q, r), "swap"))
                break
        return moves

    def _moves_SH(self, cell, pc):
        # Shaman (v5): steps 1 cell along the 4 ortho dirs that aren't the
        # two horizontal "sides", moving or capturing.  Its `uses` field is
        # the SOUL counter (+1 whenever the shaman itself captures); a
        # morph move (from_ == to == its cell, arg = target type) spends
        # souls to permanently become that type.  Never morphs to K or SH.
        moves = self._jumps(cell, pc.owner, _SH_DIRS)
        for t, cost in MORPH_COSTS.items():
            if cost <= pc.uses:
                moves.append(Move(cell, cell, "morph", t))
        return moves

    def _moves_MI(self, cell, pc):
        # Mimic (v5): moves exactly like the LAST piece that acted in the
        # game (gs.mimic_type), via a stand-in piece of that type carrying
        # the mimic's own owner/moved/uses.  Morph moves are dropped (a
        # mimic has no souls worth spending); shoots, swaps and raises are
        # copied faithfully.
        mt = self.mimic_type
        if mt == "MI" or mt not in self._GEN:
            mt = "P"   # defensive: mimics never copy mimics
        stand_in = Piece(mt, pc.owner, pc.moved, pc.uses)
        return [m for m in self._GEN[mt](self, cell, stand_in)
                if m.kind != "morph"]

    _GEN = {"K": _moves_K, "Q": _moves_Q, "R": _moves_R, "B": _moves_B,
            "N": _moves_N, "P": _moves_P, "CN": _moves_CN, "AR": _moves_AR,
            "WZ": _moves_WZ, "DR": _moves_DR, "CH": _moves_CH,
            "BM": _moves_BM, "GH": _moves_GH, "NE": _moves_NE,
            "CT": _moves_CT, "VA": _moves_VA, "GO": _moves_GO,
            "JG": _moves_JG, "SN": _moves_SN, "WD": _moves_WD,
            "SK": _moves_SK, "TF": _moves_TF, "SH": _moves_SH,
            "MI": _moves_MI}

    # -- attacks ------------------------------------------------------------

    def _find_king(self, pid):
        for c, pc in self.board.items():
            if pc.owner == pid and pc.type == "K":
                return c
        return None

    def _eff_type(self, pc):
        """The type `pc` moves and THREATENS as (v5): a Mimic borrows the
        last-acted type (gs.mimic_type); everyone else is just themselves.
        A pawn-mimic threatens by its OWNER's seat, which falls out
        naturally because the owner never changes."""
        if pc.type == "MI":
            mt = self.mimic_type
            return "P" if mt == "MI" else mt
        return pc.type

    def king_in_danger(self, pid):
        """True if any living enemy piece can capture pid's king right now."""
        kcell = self._find_king(pid)
        return kcell is not None and self._cell_attacked(kcell, pid)

    def _king_in_danger_scan(self, pid):
        """Slow reference implementation: scan every enemy pseudo move.
        Kept ONLY so tests can differentially verify _cell_attacked."""
        kcell = self._find_king(pid)
        if kcell is None:
            return False
        for c, pc in list(self.board.items()):
            if pc.owner == pid or not self._is_alive(pc.owner):
                continue
            for mv in self._pseudo_moves(c):
                # only "move" and "shoot" are capture-capable kinds; a
                # thief's swap never targets a king anyway (v5), raises
                # target empty cells, morphs target the actor's own cell
                if mv.to == kcell and mv.kind in ("move", "shoot"):
                    return True
        return False

    def _cell_attacked(self, kcell, pid):
        """Fast reverse attack test: can any living enemy capture a `pid`
        piece standing on `kcell`? Mirrors every piece's movement rules from
        the target's point of view (differentially tested against the pseudo
        move scan in the fuzz suite).

        v5: every type comparison goes through _eff_type so a Mimic
        threatens as whatever mimic_type currently is; a Thief (or a
        thief-mimic) never attacks anything; a Shaman attacks at 1 step on
        its 4 dirs only.
        """
        board = self.board
        cells = self._cells
        graves = self.graveyards
        eff = self._eff_type

        def enemy(pc):
            return (pc is not None and pc.owner != pid
                    and self._is_alive(pc.owner))

        # A warden's aura stops kind="move" captures; shoots go through it.
        shielded = self._protected(kcell, pid)

        # --- ranged shots ignore blockers AND the aura ---
        for dq, dr in ORTHO:
            pc = board.get((kcell[0] + 2 * dq, kcell[1] + 2 * dr))
            if enemy(pc) and eff(pc) == "AR":
                return True
            pc = board.get((kcell[0] + 3 * dq, kcell[1] + 3 * dr))
            if enemy(pc) and eff(pc) == "CT":
                return True
        for dq, dr in DIAG:
            pc = board.get((kcell[0] + 2 * dq, kcell[1] + 2 * dr))
            if enemy(pc) and eff(pc) == "SN":
                return True
        if shielded:
            return False

        # --- ortho rays: sliders, chargers, and the cannon's screen-jump ---
        jg_range = globals().get("JUGGERNAUT_RANGE", 5)
        for dq, dr in ORTHO:
            q, r = kcell
            seen_screen = False
            steps = 0
            while steps < 4 * self.radius:
                q += dq
                r += dr
                steps += 1
                cell = (q, r)
                if cell not in cells or cell in graves:
                    break
                pc = board.get(cell)
                if pc is None:
                    continue
                if not seen_screen:
                    if enemy(pc):
                        t = eff(pc)
                        # NB: no "TF" anywhere — thieves never attack (v5).
                        # The shaman's dir test works unsigned because
                        # _SH_DIRS is symmetric under negation.
                        if (t in ("R", "Q")
                                or (t == "DR" and steps <= 3)
                                or (t == "JG" and steps <= jg_range)
                                or (t == "BM" and steps <= 2)
                                or (steps == 1 and t in ("K", "GO", "WD",
                                                         "CH"))
                                or (steps == 1 and t == "SH"
                                    and (dq, dr) in _SH_DIR_SET)):
                            return True
                    seen_screen = True
                else:
                    # second piece on the ray: only a cannon jumps the screen
                    if enemy(pc) and eff(pc) == "CN":
                        return True
                    break

        # --- diag rays: sliders (ghosts handled as jumps below) ---
        for dq, dr in DIAG:
            q, r = kcell
            steps = 0
            while steps < 4 * self.radius:
                q += dq
                r += dr
                steps += 1
                cell = (q, r)
                if cell not in cells or cell in graves:
                    break
                pc = board.get(cell)
                if pc is None:
                    continue
                if enemy(pc):
                    t = eff(pc)
                    # NB: no "K" here — kings only capture on the 6 ortho
                    # neighbours (see _moves_K). SH gained the diagonal
                    # step in v5.1.
                    if (t in ("B", "Q")
                            or (t == "DR" and steps <= 3)
                            or (steps == 1 and t in ("NE", "VA", "WD",
                                                     "CH", "SH"))):
                        return True
                break

        # --- jumps that ignore blockers ---
        for dq, dr in KNIGHT:
            pc = board.get((kcell[0] + dq, kcell[1] + dr))
            if enemy(pc) and eff(pc) in ("N", "VA"):
                return True
        for dq, dr in ORTHO:  # champion's 2-step ortho leap
            pc = board.get((kcell[0] + 2 * dq, kcell[1] + 2 * dr))
            if enemy(pc) and eff(pc) == "CH":
                return True
        for dq, dr in DIAG:   # ghosts phase through anything within range
            for k in range(1, GHOST_RANGE + 1):
                pc = board.get((kcell[0] + k * dq, kcell[1] + k * dr))
                if enemy(pc) and eff(pc) == "GH":
                    return True
        for dq in range(-2, 3):  # wizard teleports within 2
            for dr in range(-2, 3):
                if 1 <= (abs(dq) + abs(dr) + abs(dq + dr)) // 2 <= 2:
                    pc = board.get((kcell[0] + dq, kcell[1] + dr))
                    if enemy(pc) and eff(pc) == "WZ":
                        return True

        # --- pawns and skeletons: their 3 forward capture diagonals ---
        # (a pawn-mimic threatens by its OWNER's seat: the owner drives
        # which player's forwards apply)
        for p in self.players:
            if p["pid"] == pid or not p["alive"]:
                continue
            f1, f2 = shape_edge_forward(self.shape, p["seat"])
            for cap in ((f1[0] + f2[0], f1[1] + f2[1]),
                        (2 * f1[0] - f2[0], 2 * f1[1] - f2[1]),
                        (2 * f2[0] - f1[0], 2 * f2[1] - f1[1])):
                pc = board.get((kcell[0] - cap[0], kcell[1] - cap[1]))
                if (pc is not None and pc.owner == p["pid"]
                        and eff(pc) in ("P", "SK")):
                    return True
        return False

    # -- move application ---------------------------------------------------

    def apply_move(self, pid, move):
        """Validate and execute `move` for player `pid`.

        Returns (True, None) on success, else (False, reason).
        """
        if self.winner is not None:
            return False, "Game is over"
        if pid != self.turn_pid:
            return False, "Not your turn"
        if not isinstance(move, Move):
            return False, "Malformed move"
        pc = self.board.get(move.from_)
        if pc is None or pc.owner != pid:
            return False, "No piece of yours there"
        if move not in self.legal_moves(move.from_):
            return False, "Illegal move"

        self._boom = deque()
        self._dead_kings = []
        name = self._name(pid)
        actor_type = pc.type   # v5: the mimic copies the type at move START

        if move.kind == "raise":
            # v4: raising consumes a lost Pawn but yields a Skeleton.
            self.lost[pid].remove("P")
            self.board[move.to] = Piece("SK", pid, True)
            self._log("%s's Necromancer raises a Skeleton from the dead!"
                      % name)
        elif move.kind == "swap":
            # v5 thief swap: the two pieces exchange cells; nothing dies,
            # no souls are gained.  The thief is marked moved; the OTHER
            # piece keeps its own flags untouched.
            other = self.board[move.to]
            self.board[move.to] = pc
            self.board[move.from_] = other
            pc.moved = True
            self._log("%s's %s swaps places with %s's %s." %
                      (name, PIECE_NAMES[pc.type],
                       self._name(other.owner), PIECE_NAMES[other.type]))
        elif move.kind == "morph":
            # v5 shaman morph: spend souls to permanently become move.arg;
            # nothing changes positionally, but the turn is consumed and
            # the leftover souls stay in `uses`.
            pc.uses -= MORPH_COSTS[move.arg]
            pc.type = move.arg
            self._log("%s's Shaman twists into a %s!"
                      % (name, PIECE_NAMES[move.arg]))
        elif move.kind == "shoot":
            victim = self.board[move.to]
            self._log("%s's %s shoots %s's %s!" %
                      (name, PIECE_NAMES[pc.type],
                       self._name(victim.owner),
                       PIECE_NAMES[victim.type]))
            self._kill(move.to)
            self._resolve_explosions()
        else:
            victim = self.board.get(move.to)
            if victim is not None:
                self._log("%s's %s takes %s's %s." %
                          (name, PIECE_NAMES[pc.type],
                           self._name(victim.owner),
                           PIECE_NAMES[victim.type]))
                self._kill(move.to)
            # quiet moves are not logged — the board highlight shows them
            del self.board[move.from_]
            pc.moved = True
            if pc.type == "SH":
                # v5: a shaman's `uses` are SOULS — they grow only when
                # the shaman itself captures, never on quiet moves.
                if victim is not None:
                    pc.uses += 1
            else:
                pc.uses += 1          # v4: completed moves (SK / BM care)
            self.board[move.to] = pc
            if victim is not None and pc.type == "BM":
                # A bomber that captures explodes on its landing cell and
                # dies in its own explosion (which also ends its fuse).
                self._kill(move.to)
            self._resolve_explosions()
            survivor = self.board.get(move.to)
            if survivor is pc and pc.type == "P" and self._promotes(move.to, pid):
                pc.type = "Q"
                self._log("%s's Pawn becomes a QUEEN!" % name)
            elif survivor is pc and pc.type == "SK" and pc.uses >= 3:
                # Skeletons crumble after their 3rd completed move.
                del self.board[move.to]
                self.lost[pid].append("SK")
                self._log("%s's Skeleton crumbles to dust." % name)
            elif survivor is pc and pc.type == "BM" and pc.uses >= 10:
                # The fuse runs out on the 10th completed move: the bomber
                # detonates at its destination after the move resolves.
                self._log("%s's Bomber's fuse runs out!" % name)
                self._kill(move.to)
                self._resolve_explosions()

        # v5: the Mimic copies the LAST action — but never another Mimic.
        # move/shoot record the actor's type at move start; swap, raise and
        # morph record the piece that owns the trick (TF / NE / SH).
        if actor_type != "MI":
            self.mimic_type = {"swap": "TF", "raise": "NE",
                               "morph": "SH"}.get(move.kind, actor_type)

        for owner in self._dead_kings:
            if self._is_alive(owner):
                self.eliminate(owner, "king captured")

        if self.winner is None:
            self._advance_turn()
        return True, None

    def _kill(self, cell):
        """Remove the piece on `cell` as a casualty (records lost[], queues
        bomber explosions, notes dead kings for later elimination)."""
        pc = self.board.pop(cell)
        self.lost.setdefault(pc.owner, []).append(pc.type)
        if pc.type == "BM":
            self._boom.append(cell)
        elif pc.type == "K":
            self._dead_kings.append(pc.owner)
        return pc

    def _resolve_explosions(self):
        """Drain the explosion queue (BFS); chain reactions terminate because
        every explosion corresponds to a bomber removed from the board."""
        while self._boom:
            cq, cr = self._boom.popleft()
            self._log("BOOM! A Bomber explodes!")
            for dq, dr in ORTHO:
                t = (cq + dq, cr + dr)
                occ = self.board.get(t)
                # Kings AND Golems are immune to explosions.
                if occ is not None and occ.type not in ("K", "GO"):
                    self._log("...the blast destroys %s's %s." %
                              (self._name(occ.owner),
                               PIECE_NAMES[occ.type]))
                    self._kill(t)

    # -- eliminations, wins, turn order --------------------------------------

    def eliminate(self, pid, reason):
        """Mark `pid` dead and remove ALL their pieces from the board.

        The cleanup does NOT trigger bomber explosions; lost[pid] is kept.
        Used for king capture and for disconnects (called by the server).
        """
        p = self._player(pid)
        if p is None or not p["alive"]:
            return
        p["alive"] = False
        self.graves_left[pid] = 1   # v4: one tile-curse, granted on death
        for cell in [c for c, pc in self.board.items() if pc.owner == pid]:
            del self.board[cell]
        self._log("%s is eliminated (%s)." % (self._name(pid), reason))
        self._check_win()
        if self.winner is None and self.turn_pid == pid:
            # The player to move vanished (e.g. disconnect): pass the turn on.
            self._advance_turn()

    def apply_grave(self, pid, cell):
        """A DEAD player curses one empty tile, turning it into a graveyard.

        Valid iff `pid` is dead, has a curse left (granted on elimination),
        and `cell` is an on-board EMPTY cell that is not already a
        graveyard.  NOT turn-based: dead players may do this at any time
        and the turn does not advance.  Returns (True, None) on success,
        else (False, reason).
        """
        try:
            cell = (int(cell[0]), int(cell[1]))
        except (TypeError, ValueError, IndexError):
            return False, "Malformed cell"
        p = self._player(pid)
        if p is None:
            return False, "No such player"
        if p["alive"]:
            return False, "Only dead players can curse tiles"
        if self.graves_left.get(pid, 0) < 1:
            return False, "No curses left"
        if cell not in self._cells:
            return False, "Not a board cell"
        if cell in self.board:
            return False, "That tile is occupied"
        if cell in self.graveyards:
            return False, "Already a graveyard"
        self.graveyards.add(cell)
        self.graves_left[pid] -= 1
        self._log("%s curses a tile from beyond the grave"
                  % self._name(pid))
        return True, None

    def force_skip(self, pid):
        """Skip `pid`'s turn because their move timer expired.

        No-op if the game is over or it is not actually `pid`'s turn.
        Called by the server's timer thread.
        """
        if self.winner is not None or pid != self.turn_pid:
            return
        self._log("%s ran out of time — turn skipped" % self._name(pid))
        self._advance_turn()

    def end_by_time(self):
        """End the game because the total clock expired.

        Winner = the alive player with the most pieces on the board;
        ties -> draw (winner = -1).  No-op if the game is already over.
        """
        if self.winner is not None:
            return
        counts = {p["pid"]: 0 for p in self.players if p["alive"]}
        for pc in self.board.values():
            if pc.owner in counts:
                counts[pc.owner] += 1
        best = max(counts.values(), default=0)
        leaders = [pid for pid, c in counts.items() if c == best]
        if len(leaders) == 1:
            self.winner = leaders[0]
            self._log("Time! %s wins with the most pieces on the board."
                      % self._name(leaders[0]))
        else:
            self.winner = -1
            self._log("Time! Draw — tied on pieces.")

    def _check_win(self):
        if self.winner is not None:
            return
        alive = [p for p in self.players if p["alive"]]
        if len(alive) == 1:
            self.winner = alive[0]["pid"]
            self._log("%s wins!" % alive[0]["name"])
        elif not alive:
            self.winner = -1
            self._log("Draw — nobody left.")

    def _advance_turn(self):
        """Advance to the next living player who has a legal move.

        Moveless living players are skipped (and logged); if a full circle
        finds nobody with a move, the game is a draw (winner = -1).
        """
        if self.winner is not None:
            return
        order = [p["pid"] for p in self.players]
        idx = order.index(self.turn_pid) if self.turn_pid in order else 0
        n = len(order)
        for i in range(1, n + 1):
            cand = order[(idx + i) % n]
            if not self._is_alive(cand):
                continue
            if self.all_legal_moves(cand):
                self.turn_pid = cand
                return
            self._log("%s has no moves — skipped" % self._name(cand))
        self.winner = -1
        self._log("Draw — no player can move.")

    # -- serialization -------------------------------------------------------

    def to_dict(self):
        """Exact JSON-safe schema relied on by net.py and main.py."""
        return {
            "radius": self.radius,
            "shape": self.shape,
            "players": [{"pid": p["pid"], "name": p["name"], "seat": p["seat"],
                         "alive": bool(p["alive"]), "color": p["color"]}
                        for p in self.players],
            "turn_pid": self.turn_pid,
            "board": [[q, r, pc.type, pc.owner, 1 if pc.moved else 0,
                       pc.uses]
                      for (q, r), pc in sorted(self.board.items())],
            "lost": {str(pid): list(types) for pid, types in self.lost.items()},
            "winner": self.winner,
            "log": list(self.log[-50:]),
            "graveyards": [[q, r] for q, r in sorted(self.graveyards)],
            "graves_left": {str(pid): int(n)
                            for pid, n in self.graves_left.items()},
            "mimic": self.mimic_type,
        }

    @staticmethod
    def from_dict(d):
        """Rebuild a GameState from to_dict() output (exact round-trip).

        Back-compat: v1 dicts have no "shape" key (default "hexagon");
        pre-v4 dicts have 5-element board rows (uses defaults to 0) and no
        "graveyards" / "graves_left" keys (default empty); pre-v5 dicts
        have no "mimic" key (default "P").
        """
        gs = GameState(int(d["radius"]), str(d.get("shape", "hexagon")))
        gs.players = [{"pid": int(p["pid"]), "name": str(p["name"]),
                       "seat": int(p["seat"]), "alive": bool(p["alive"]),
                       "color": int(p["color"])}
                      for p in d["players"]]
        gs.turn_pid = int(d["turn_pid"])
        for row in d["board"]:
            q, r, t, owner, moved = row[:5]
            uses = int(row[5]) if len(row) > 5 else 0
            gs.board[(int(q), int(r))] = Piece(t, int(owner), bool(moved),
                                               uses)
        gs.lost = {int(pid): list(types)
                   for pid, types in d.get("lost", {}).items()}
        for p in gs.players:
            gs.lost.setdefault(p["pid"], [])
        w = d.get("winner")
        gs.winner = None if w is None else int(w)
        gs.log = [str(x) for x in d.get("log", [])]
        gs.graveyards = {(int(q), int(r))
                         for q, r in d.get("graveyards", [])}
        gs.graves_left = {int(pid): int(n)
                          for pid, n in d.get("graves_left", {}).items()}
        gs.mimic_type = str(d.get("mimic", "P"))
        return gs
