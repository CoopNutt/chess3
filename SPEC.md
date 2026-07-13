# CHESS 3 — Technical Specification

> **v2 addendum at the bottom of this file** (board shapes, match settings,
> timers, 3 swappable troops, movement diagrams, protocol v2). v2 overrides
> v1 where they conflict.

A hexagonal multiplayer chess variant for 2–6 players with 8 new troop types and
lobby-code networking. Python 3.14, pygame-ce 2.5.7, stdlib-only otherwise.

Directory: `C:\Users\iceda\Desktop\tung\chess3\`

```
chess3/
  engine.py      # pure game logic, NO pygame imports, fully headless/testable
  net.py         # server + client + lobby codes + UPnP, NO pygame imports
  icons.py       # vector piece drawing, imports pygame only
  main.py        # pygame app (menus, lobby, game screen)
  tests/
    __init__.py  # empty
    test_engine.py
    test_net.py
  build.bat
  README.md
```

Tests use **stdlib `unittest`** (pytest is NOT installed). Run:
`python -m unittest discover -s tests -v` from the chess3 dir.
All modules must import cleanly on Windows, Python 3.14.

---

## 1. Hex geometry (engine.py)

Axial coordinates `(q, r)`, pointy-top cells. Implicit third coord `s = -q - r`.

```python
ORTHO = [(1,0),(0,1),(-1,1),(-1,0),(0,-1),(1,-1)]        # 6 dirs, rotational order
DIAG  = [(2,-1),(1,1),(-1,2),(-2,1),(-1,-1),(1,-2)]      # 6 diag dirs, rotational order
KNIGHT = [(3,-1),(3,-2),(2,1),(1,2),(-1,3),(-2,3),
          (-3,1),(-3,2),(-2,-1),(-1,-2),(1,-3),(2,-3)]   # 12 jumps

def hex_dist(a, b) -> int:      # (|dq| + |dr| + |dq+dr|) // 2
def rotate60(cell, times=1):    # one step: (q,r) -> (-r, q+r); times may be 0..5
def board_cells(radius) -> set: # all (q,r) with max(|q|,|r|,|q+r|) <= radius
```

Cell counts: radius R -> 3R²+3R+1 cells (R=6: 127, R=7: 169, R=8: 217, R=9: 271).

**Important hex rule: diagonal movement is never blocked by the two cells it
passes between.** A diag ray is blocked only by pieces sitting ON cells of the
ray itself. (Standard Glinski-style hex chess rule.)

### Board edges & seats

The hexagon has 6 edges, indexed in rotational order:

| edge | constraint  | forward dirs F1, F2   |
|------|-------------|------------------------|
| 0    | r = R       | (0,-1), (1,-1)         |
| 1    | q + r = R   | (0,-1), (-1,0)         |
| 2    | q = R       | (-1,0), (-1,1)         |
| 3    | r = -R      | (0,1), (-1,1)          |
| 4    | q + r = -R  | (0,1), (1,0)           |
| 5    | q = -R      | (1,0), (1,-1)          |

Each player sits on one edge; their pawns advance using the two forward dirs.
`rotate60` applied once maps edge i cells onto edge (i-1) mod 6 cells (this is
used by the renderer to put the local player's edge at the bottom; engine just
needs to expose `EDGE_FORWARD: list[tuple[F1,F2]]` and a function
`edge_row(edge_idx, radius, row) -> list[cell]` returning the cells of the row
at distance `row` from that edge (row 0 = on the edge), **ordered consistently
along the edge** (any consistent order; center the army within the row).

```python
SEAT_EDGES  = {2:[0,3], 3:[0,2,4], 4:[0,1,3,4], 5:[0,1,2,3,4], 6:[0,1,2,3,4,5]}
BOARD_RADIUS = {2:6, 3:7, 4:11, 5:11, 6:11}
```

### Army layout (24 pieces per player) — QUIET START invariant

- Row 0 (7, centered): `DR N R K Q R N`
- Row 1 (8, centered, shifted +1): `BM NE GH B CN CH AR WZ`
- Row 2 (4 pawns, centered)
- Row 3 (5 pawns, centered)

The pawns form a STAGGERED double shield: hex diagonals hop two rows per
step, so a single pawn row cannot block enemy sliders — two staggered rows
cover both parities. This exact (layout, shifts, radii) combination was
machine-searched so that the start position is QUIET at every player count:
no player has any legal capture, shoot, or instant promotion on ply 1, and
armies never collide. `TestQuietStart` pins this; re-run the search before
changing any of it.

Every army contains all 8 new troop types plus K, Q, 2xR, 2xN, 1xB, 9xP.

---

## 2. Piece types & movement (engine.py)

Type ids (strings): `"K" "Q" "R" "B" "N" "P"` classic;
`"CN" "AR" "WZ" "DR" "CH" "BM" "GH" "NE"` new.

```python
PIECE_NAMES = {"K":"King","Q":"Queen","R":"Rook","B":"Bishop","N":"Knight","P":"Pawn",
 "CN":"Cannon","AR":"Archer","WZ":"Wizard","DR":"Dragon","CH":"Champion",
 "BM":"Bomber","GH":"Ghost","NE":"Necromancer"}
PIECE_DESCRIPTIONS = { ... one plain-English line per type, used by help UI ... }
```

Movement (all "slide" moves stop at first occupied cell; capture if enemy):

- **K**: 1 step, any of ORTHO or DIAG. (No castling.)
- **Q**: slide along ORTHO and DIAG.
- **R**: slide along ORTHO.
- **B**: slide along DIAG.
- **N**: jump to any KNIGHT offset (leaps).
- **P** (owner's edge forwards F1, F2):
  - Non-capture step: F1 or F2 to an EMPTY cell.
  - First move (piece.moved == False): may also do 2×F1 or 2×F2 if BOTH cells empty. No en passant.
  - Capture only: the 3 forward diagonals `F1+F2`, `2*F1-F2`, `2*F2-F1`
    (each is a DIAG dir at hex distance 2; never blocked, capture-only, no quiet move there).
  - **Promotion**: when a pawn ends its move on a board-edge cell
    (max(|q|,|r|,|q+r|) == R) lying on the boundary line of a FAR edge —
    circular edge-index distance >= 2 from the owner's home edge. A
    neighboring army's back rank never promotes. Raised pawns (necromancer)
    promote the same way when they later move.
- **CN Cannon**: slides along ORTHO like a rook but ONLY to empty cells (cannot
  capture by sliding). Captures by "jumping": along an ORTHO ray, exactly one
  intervening piece (any color, the "screen") then the FIRST piece beyond the
  screen — if that piece is an enemy, cannon may capture it (moving onto its cell).
- **AR Archer**: moves 1 ORTHO step to an EMPTY cell only (never captures by
  moving). Special "shoot": captures an enemy piece at EXACTLY 2 cells along an
  ORTHO dir (cell `from + 2*d`), regardless of whether the intermediate cell is
  occupied. The archer DOES NOT MOVE; the target is removed. kind="shoot".
- **WZ Wizard**: teleports to any cell at hex_dist 1..2 (18 cells), ignoring
  all blockers. Lands on empty (move) or enemy (capture).
- **DR Dragon**: slides along ORTHO and DIAG, max 3 steps per ray.
- **CH Champion**: jumps (ignores blockers) to: 1 ORTHO step, 2×ORTHO (same dir), or 1 DIAG step. 18 targets.
- **BM Bomber**: slides along ORTHO, max 2 steps. **Explodes** whenever it
  captures OR is destroyed by any means (captured, shot, exploded): every piece
  on the 6 ORTHO-adjacent cells of the bomber's cell dies, EXCEPT Kings
  (kings are immune to explosions). The bomber itself dies in its own explosion.
  If the bomber captured by moving, explosion is centered on its landing cell.
  Chain reactions: a bomber destroyed by an explosion explodes too. Must terminate.
- **GH Ghost**: slides along DIAG, max 3 steps (engine.GHOST_RANGE), PASSING
  THROUGH occupied cells. May land on any empty cell (move) or enemy-occupied
  cell (capture) along the ray. Friendly-occupied cells cannot be landed on
  but are passed through.
- **NE Necromancer**: moves/captures 1 DIAG step. Special "raise": if the owner
  has at least one lost pawn (a "P" in lost[owner]), the necromancer may, as its
  turn, place a new pawn (moved=True) on any EMPTY ORTHO-adjacent cell,
  consuming one "P" from lost[owner]. kind="raise", from_=necro cell, to=target cell. The necromancer does not move.

"Attacks" for king-danger purposes = all capture-capable destinations
(pawn's 3 capture diags; archer's shoot cells; cannon's jump-capture cells; etc.).

---

## 3. Game state & rules (engine.py)

```python
class Piece:
    __slots__ = ("type", "owner", "moved")   # owner = pid (int)

class Move:
    # kind in {"move", "shoot", "raise"}
    def __init__(self, from_, to, kind="move"): ...
    def to_dict(self) -> dict   # {"from":[q,r],"to":[q,r],"kind":...}
    @staticmethod
    def from_dict(d) -> "Move"  # raises ValueError on malformed input
    def __eq__ / __hash__       # value semantics (used to validate client moves)

class GameState:
    radius: int
    board: dict[tuple[int,int], Piece]
    players: list[dict]   # {"pid":int,"name":str,"seat":int(edge idx),"alive":bool,"color":int}
    turn_pid: int
    lost: dict[int, list[str]]   # piece types each pid has LOST (fuels necromancer)
    winner: int | None           # None=ongoing, pid=winner, -1=draw
    log: list[str]               # human-readable event lines, keep last 200

    @staticmethod
    def new_game(players: list[tuple[int, str]]) -> "GameState"
        # assigns seats via SEAT_EDGES[len(players)], radius via BOARD_RADIUS,
        # color i = i-th player, places armies, turn = players[0]

    def legal_moves(self, cell) -> list[Move]      # [] if no piece / dead owner / game over
    def all_legal_moves(self, pid) -> list[Move]
    def apply_move(self, pid, move: Move) -> tuple[bool, str|None]
        # False+"reason" if: game over, not pid's turn, move not in legal_moves.
        # On success: mutate board, handle captures -> lost[], explosions (chained),
        # promotion, king-capture eliminations, win check, advance turn, log lines.
    def king_in_danger(self, pid) -> bool          # any living enemy attacks pid's king
    def eliminate(self, pid, reason: str)          # mark dead, REMOVE all their pieces
        # (removal does NOT trigger bomber explosions), log it, check win.
        # Used for king capture and for disconnects (called by server).
    def to_dict(self) -> dict
    @staticmethod
    def from_dict(d) -> "GameState"
```

Rules details:

- **No check/checkmate.** Kings are captured like any piece. When a player's
  king is captured (or shot / any death), that player is eliminated via
  `eliminate()`. Moving your own king into danger is legal.
- **Elimination removes all of that player's remaining pieces from the board**
  (they vanish; no explosions triggered by this cleanup). Their lost[] stays.
- **Win**: when <= 1 player alive after any event, winner = that pid (game over).
- **Turn order**: ascending players list order, skipping dead players.
  After apply_move, advance to next alive player. If that player has NO legal
  moves, log "X has no moves — skipped" and keep advancing; if a full loop finds
  nobody (all alive players moveless), set winner = -1 (draw).
- Explosion resolution: BFS/queue; each bomber explodes at most once. Deaths
  from explosions go to lost[] normally; king cannot die to explosion; if a
  king's owner dies some other way in the same resolution, handle eliminations after
  the explosion queue settles.
- apply_move for "shoot": target dies (with bomber-chain handling if target is a bomber), shooter stays. For "raise": pawn placed, lost pawn consumed.
- Captures by any means append the VICTIM's type to lost[victim_owner].

### Serialization (exact schema — net.py and main.py rely on it)

```python
state_dict = {
  "radius": int,
  "players": [{"pid":int,"name":str,"seat":int,"alive":bool,"color":int}, ...],
  "turn_pid": int,
  "board": [[q, r, type_str, owner_pid, moved_int01], ...],
  "lost": {str(pid): [type_str, ...], ...},     # JSON keys are strings
  "winner": None | int,
  "log": [str, ...],                             # last 50 entries suffice
}
```

`from_dict(to_dict())` must round-trip exactly (winner, turn, every piece+moved flag).

---

## 4. Networking (net.py)

TCP, newline-delimited JSON (UTF-8, one JSON object per line, `\n` terminator).
Default port `47733`. Protocol version `1`. No pygame imports. Uses engine.py.

### Messages

Client -> Server:
- `{"t":"hello","name":str,"ver":1}` — first message after connect.
- `{"t":"move","move":{...Move.to_dict()...}}`
- `{"t":"leave"}` — polite quit.

Server -> Client:
- `{"t":"welcome","pid":int}` — reply to hello (host is always pid 0).
- `{"t":"lobby","players":[{"pid","name","color"}],"max":6,"min":2}` — sent to
  everyone whenever lobby membership changes (and to a new joiner immediately).
- `{"t":"start","state":state_dict}`
- `{"t":"state","state":state_dict,"last_move":{"pid":int,"move":{...}}|None}` — after every accepted move AND after eliminations from disconnects.
- `{"t":"error","msg":str}` — e.g. rejected move ("Not your turn"), lobby full.
- `{"t":"gameover","winner":int|-1,"name":str}` — sent alongside final state.
- `{"t":"kicked","reason":str}` — lobby full / game already started / bad hello; server closes socket after.

### Server

```python
class HostServer:
    def __init__(self, host_name: str, port: int = 47733)
    def start(self) -> None            # binds 0.0.0.0, starts accept thread; raises OSError if port busy
    # Host player occupies pid 0 WITHOUT a socket (they're in-process).
    events: queue.Queue                # dicts for the host UI (same schema as client events, below)
    def start_game(self) -> tuple[bool, str|None]   # False if <2 players; builds GameState, broadcasts start
    def submit_host_move(self, move_dict) -> None   # host's own moves enter here
    def player_count(self) -> int
    def close(self) -> None            # closes all sockets, stops threads
```

Behavior:
- Joins after 6 players or after game start -> `kicked` + close that socket.
- A move message from a client is validated with `GameState.apply_move(pid, ...)`;
  on success broadcast `state` to all clients AND push it to host `events`;
  on failure send `error` to just that client.
- Client disconnect (socket error/EOF/leave): in lobby -> remove + broadcast lobby;
  in game -> `eliminate(pid, "disconnected")`, broadcast state (+ gameover if that ends it).
- All GameState access under one `threading.Lock`.
- Malformed JSON line or oversized line (> 64 KB) -> drop that client safely.

### Client

```python
class NetClient:
    def __init__(self)
    def connect(self, ip: str, port: int, name: str, timeout=6.0) -> None  # raises on failure, sends hello, waits for welcome/kicked
    pid: int
    events: queue.Queue    # every server message as parsed dict, plus {"t":"disconnected"} on socket loss
    def send_move(self, move_dict) -> None
    def close(self) -> None
```

Reader thread pushes every parsed server message into `events`. UI polls with
`get_nowait()`. Never blocks the UI thread.

### Lobby codes

6 bytes = IPv4 (4) + port big-endian (2) -> Crockford base32 (alphabet
`0123456789ABCDEFGHJKMNPQRSTVWXYZ`, no I/L/O/U) -> 10 chars -> `XXXXX-XXXXX`.

```python
def encode_code(ip: str, port: int) -> str
def decode_code(text: str) -> tuple[str, int]
    # tolerant: strips spaces/dashes, uppercases, maps I->1, L->1, O->0;
    # ALSO accepts raw "ip:port" and bare "ip" (default port). ValueError if invalid.
def get_lan_ip() -> str            # UDP-connect-to-8.8.8.8 trick, fallback 127.0.0.1
def get_public_ip(timeout=3.0) -> str | None   # https://api.ipify.org, None on any failure
```

### UPnP (best effort, all failures swallowed -> (False, reason))

```python
def upnp_map_port(port: int, timeout=3.0) -> tuple[bool, str]
def upnp_unmap_port(port: int) -> None
```

Minimal stdlib implementation: SSDP M-SEARCH (UDP multicast 239.255.255.250:1900,
ST InternetGatewayDevice:1), parse LOCATION, GET device XML, find
WANIPConnection:1 (or WANPPPConnection:1) controlURL, SOAP AddPortMapping
(TCP, internal client = get_lan_ip(), lease 0, description "Chess3").
Never raises; never blocks > ~timeout*2 total. Tests must NOT exercise real UPnP.

---

## 5. Icons (icons.py)

```python
def draw_piece(surface, ptype: str, body_color: tuple, size: int, center: tuple) -> None
```

Draws a piece at `center` fitting a circle of diameter ~`size`: a filled disc in
`body_color` with a dark outline, plus a white-with-dark-outline vector glyph
unique per type (crown for K, castle for R, bomb+fuse for BM, pointed hat for WZ,
bow+arrow for AR, skull for NE, wavy sheet for GH, etc. — every one of the 14
types must be visually distinct at size 36). Pure pygame.draw primitives
(polygon/circle/arc/line) — NO fonts, NO image files. Must render without a
display (works with SDL_VIDEODRIVER=dummy on plain Surfaces).

Also: `def render_all_preview(cell=48) -> pygame.Surface` returning a grid of
all 14 types (used by help screen & manual eyeballing).

PLAYER_COLORS (6, in pid order) live in icons.py:
`[(238,238,238),(72,72,84),(214,74,74),(76,118,224),(232,196,66),(158,84,214)]`
(white, black, red, blue, gold, purple).

---

## 6. Tests

`tests/test_engine.py` (unittest) must cover at least:
- board_cells counts for R=6..9; edge_row cells lie on board and on the right line.
- new_game for 2..6 players: 24 pieces each, no overlaps, all on board, kings present, correct seats.
- Pawn: quiet steps, double first move (blocked variants), the 3 capture diags (and that quiet moves cannot go there), promotion on far edge incl. auto-queen, no promotion on own home edge.
- Each new troop: a crafted-position test of its signature ability
  (cannon screen-jump incl. "cannot slide-capture"; archer shoot-over-blocker & no move-capture; wizard teleport over walls;
  dragon 3-cap; champion leap; bomber explosion + chain + king immunity; ghost phase-through; necro raise consuming lost pawn & requiring one).
- King capture -> elimination -> pieces removed -> win detection (2p and 3p).
- Turn skipping when a player has no moves; draw when nobody does.
- Serialization round-trip equality.
- **Fuzz: for n_players in (2,3,6): play 3 full random games (random choice of
  all_legal_moves of current player, up to 400 plies), asserting after every move:**
  board pieces all on valid cells, every piece's owner is alive, turn_pid is alive
  (unless winner set), lost[] types are valid, to_dict/from_dict round-trips.

`tests/test_net.py`:
- encode/decode lobby code round-trip; tolerant decode ("k7x2p 9qzlm", lowercase, I/O/L confusables); "ip:port" and bare-ip passthrough; ValueError on garbage.
- Real localhost game over TCP (bind port 0-style: allow passing port, pick a free ephemeral port via socket bind trick): host + 3 clients join, lobby broadcasts seen,
  7th client kicked when full is NOT tested (only 4 sockets) but: join-after-start kicked IS tested.
  start_game with 1 player fails; with 4 total succeeds; clients receive start.
  Play a scripted opening: read state, compute a legal move for whoever's turn is
  (using engine on the client side), submit; wrong-turn submission -> error msg.
  Then random-play a full game through the server until gameover or 300 plies —
  asserting every client converges to identical state dicts.
- Mid-game disconnect: close one client socket; others receive state with that player eliminated.
- No UPnP / no public-IP calls in tests.

Both test files: `sys.path` bootstrap so `import engine` works when run from the
chess3 dir via `python -m unittest discover -s tests`.

---

## 7. main.py (UI) — summary

Resizable window 1280x800 (min 960x640), 60 FPS. Screens: MENU (name entry,
Host / Join / How to Play / Quit), HOST_LOBBY (lobby codes shown big + copy
buttons, UPnP status line, player list, Start enabled at >=2), JOIN (code entry
box, status), CLIENT_LOBBY, GAME, GAME_OVER overlay, HELP overlay (all 14
pieces w/ icons + descriptions, toggle H). Board rendered with the local
player's home edge rotated to the bottom via rotate60. Click piece -> highlight
legal moves (dot=quiet, ring=capture, star=special shoot/raise). Turn banner, player
strip with alive/dead + "YOU", king-danger red pulse, last-8 log lines, lerped
move animation (~140ms), explosion flash. Pawn promotion is auto (no dialog).
Host runs HostServer + plays via submit_host_move/events; joiner uses NetClient.

---

# V2 ADDENDUM

## V2.1 Board shapes (engine.py)

Cells are ALWAYS axial hex cells; only the board OUTLINE varies.
`shape` is one of `"hexagon" | "square" | "triangle" | "octagon"`.

```python
SHAPE_NAMES = {"hexagon": "Hexagon", "square": "Square",
               "triangle": "Triangle", "octagon": "Octagon"}
SHAPE_MAX_PLAYERS = {"hexagon": 6, "octagon": 6, "square": 4, "triangle": 3}
# sizes come from the quiet-start search (see V2.6); structure:
SHAPE_SIZE = {shape: {n_players: size_int}}

def shape_cells(shape, size) -> set[(q, r)]
def shape_num_edges(shape) -> int              # hexagon/octagon 6, square 4, triangle 3
def shape_seat_edges(shape, n) -> list[int]
def shape_edge_forward(shape, edge) -> ((F1), (F2))
def shape_edge_row(shape, edge, size, row) -> list[cell]   # ordered, ONLY cells in shape_cells
def shape_on_edge_line(shape, cell, edge, size) -> bool
def shape_edge_dist(shape, cell, edge, size) -> int        # cell distance from edge line
def shape_orient(shape, cell, seat, size) -> cell          # DISPLAY transform (see below)
def shape_promotes(shape, seat_edge, cell, size) -> bool   # boundary-cell promotion test
```

- **hexagon** (size=R): cells max(|q|,|r|,|q+r|) <= R. Edges/forwards/rows/seats
  exactly as v1. Promotion: boundary cell on an edge line with circular
  edge-index distance >= 2 from seat edge. orient = rotate60(cell, seat).
- **square** (size=S): cells 0<=q<S, 0<=r<S (a rhombus on hex cells; label "Square").
  Edges in ring order: 0: r=S-1, 1: q=S-1, 2: r=0, 3: q=0.
  Forwards: e0 (0,-1),(1,-1); e1 (-1,0),(-1,1); e2 (0,1),(-1,1); e3 (1,0),(1,-1).
  Rows: e0 row j = cells r=S-1-j ordered by q asc; e2 row j = r=j ordered by q desc;
  e1 row j = q=S-1-j ordered by r desc; e3 row j = q=j ordered by r asc.
  (Ordering rule: consistent handedness so armies face each other symmetrically.)
  SEATS: 2p [0,2], 3p [0,1,2], 4p [0,1,2,3]. Promotion: OPPOSITE edge only
  ((seat+2)%4). orient: seat0 identity; seat2 (q,r)->(S-1-q, S-1-r);
  seat1 (q,r)->(r,q); seat3 (q,r)->(S-1-r, S-1-q).
- **triangle** (size=T): cells q>=0, r>=0, q+r<=T. Edges: 0: r=0, 1: q+r=T, 2: q=0.
  Forwards: e0 (0,1),(-1,1)->INVALID, use (0,1),(1,... CORRECTION, forwards must
  keep pawns inside the wedge: e0: (0,1) and (1,0)? NO — definitive table:
  e0 (r=0): F1=(0,1), F2=(-1,1)   [both increase r]
  e1 (q+r=T): F1=(0,-1), F2=(-1,0) [both decrease q+r]
  e2 (q=0): F1=(1,0), F2=(1,-1)    [both increase q]
  A pawn stepping off-board simply has no such move (moves are filtered by
  shape_cells membership like every other move).
  Rows: e0 row j = cells r=j ordered by q asc; e1 row j = cells q+r=T-j ordered
  by q asc; e2 row j = cells q=j ordered by r asc.
  SEATS: 2p [0,1], 3p [0,1,2]. Promotion: boundary cell NOT on own edge line
  with shape_edge_dist(own edge) >= (2*T)//3. orient: identity for all seats
  (the UI highlights your home edge instead of rotating).
- **octagon** (size=R, TRIM=3): hexagon cells minus every cell within
  hex_dist < TRIM of any of the 6 corner cells (R,0),(0,R),(-R,R),(-R,0),(0,-R),(R,-R).
  Edges/forwards/seats/promotion/orient: same as hexagon (rows/edge lines are
  the hexagon ones filtered to surviving cells; boundary test for promotion =
  cell on hexagon edge line AND in cells).

`GameState.new_game(players, radius=None, shape="hexagon", swaps=None)`;
`GameState` gains `.shape`; `to_dict()` gains `"shape"` (from_dict defaults
"hexagon"). ALL geometry callsites (pawn forwards, promotion, rows, boundary)
go through the shape_* functions. `board_cells(radius)` stays as the hexagon
helper (back-compat); internal code uses `shape_cells`.

## V2.2 Three new swappable troops (engine.py + icons)

- **CT Catapult**: moves 1 ORTHO step to EMPTY cells only. Special shoot
  (kind="shoot"): destroys an enemy at EXACTLY 3 cells along an ORTHO ray
  (cell + 3*d), ignoring blockers, without moving. CANNOT target a Golem.
- **VA Valkyrie**: jumps (ignoring blockers) to KNIGHT offsets OR 1 DIAG step;
  lands on empty or enemy.
- **GO Golem**: moves/captures 1 ORTHO step. IMMUNE to kind="shoot" (archer,
  catapult may not target it: EXCLUDE golem cells from their shoot targets)
  and to bomber explosions (survives like a King). Normal move-captures kill it.

Army swaps: `swaps` is a dict mapping a DEFAULT troop type to a replacement in
{"CT","VA","GO"} (each replacement used at most once), e.g.
{"CN": "CT", "GH": "VA"}. Swappable defaults: CN AR WZ CH BM GH NE DR.
new_game applies the substitution to a copy of _ARMY_ROWS.

PIECE_NAMES/PIECE_DESCRIPTIONS gain the 3 types. ALL descriptions rewritten in
casual modern gamer English (short, punchy, no jargon like "orthogonal" — say
"straight" / "diagonal" / "tiles").

## V2.3 Match settings + timers (net.py)

```python
DEFAULT_SETTINGS = {"shape": "hexagon", "move_secs": 0, "total_mins": 0, "swaps": {}}
# move_secs in {0,15,30,60,120}; total_mins in {0,5,10,20,30}; 0 = off
```

- `HostServer.set_settings(partial_dict)` (host UI calls directly, no wire
  message) validates + merges, then re-broadcasts lobby. `lobby` message gains
  `"settings"`. Joining players see them.
- start_game passes shape/swaps into new_game; rejects if player count >
  SHAPE_MAX_PLAYERS[shape] ("Square maps allow up to 4 players").
- **Timers, server-enforced** (thread, 0.5s tick, same locking discipline:
  build under _lock, emit under _out_lock):
  - move timer: when the player to move has used > move_secs, call
    `engine force-skip`: `gs.force_skip(pid)` = log "NAME ran out of time —
    turn skipped", advance turn (existing skip semantics). Broadcast state
    (last_move None). Timer resets whenever turn_pid changes.
  - total timer: starts at game start; at expiry call `gs.end_by_time()`:
    winner = alive pid with the most pieces on the board; ties -> winner=-1
    (draw); log it. Broadcast state + gameover.
- `state` messages gain `"clock": {"move_left": int|None, "total_left": int|None}`
  (seconds remaining, None when that timer is off).
- `PROTOCOL_VERSION = 2`; server KICKS hello with ver != 2
  (reason "version mismatch — ask the host for the new Chess3.exe").

engine.py adds `force_skip(pid) -> None` and `end_by_time() -> None` with the
exact semantics above (both no-ops if game already over).

## V2.4 Movement diagrams (new file diagrams.py)

```python
def movement_diagram(ptype: str, width: int = 240) -> pygame.Surface
```
Renders a small hexagon mini-board (radius 3), the piece at center (player
color index 3 = blue body), markers computed from REAL engine movegen (never
hand-drawn): green dot = quiet move, red ring = capture cell, red crosshair =
shoot target. Per-type demo setups (extra gray pieces owner=1) illustrate the
signature trick: CN gets a screen piece + target beyond; AR/CT get targets at
their shoot range; GH gets a blocker it phases through; BM shows explosion
radius as orange hatching on the 6 neighbors of a capture target; NE shows a
raise marker. Pawn uses seat edge 0 forwards. Cache surfaces per (type,width).
Imports engine + icons; no file assets.

## V2.5 UI v2 (main.py — themes, friends, settings, red tiles)

- **Themes**: THEMES dict (Classic/Midnight/Forest/Ember/Ice), each defining
  BG, PANEL, PANEL_LIGHT, ACCENT, CELL_SHADES trio, GOOD/BAD kept readable.
  set_theme(name) rebinds the module color globals; choice persisted in cfg.
- **Red capture tiles**: on YOUR turn, tiles of enemy pieces that ANY of your
  pieces could capture this turn (move-capture or shoot) get a red tint +
  thin red outline. Computed once per state in BoardView.set_state.
- **Friends & recents**: cfg stores friends[], recent_players[], recent_lobbies[]
  (code+host name). FRIENDS screen from menu: add/remove friends, shows recent
  players with "friend" toggle; JOIN screen shows up to 3 recent lobbies as
  one-click fill buttons. Everyone you finish a lobby/game with is recorded.
- **Host settings UI**: settings panel in HOST_LOBBY: shape picker (disabled
  options when too many players joined), move-timer + total-timer cyclers,
  3 swap rows (Catapult/Valkyrie/Golem each: OFF or replaces <default troop>,
  no duplicate targets). Joiner lobby displays the settings read-only.
- **Timer HUD**: move timer arc/number near the turn banner (urgent pulse <10s),
  total clock top-right; both driven by the last "clock" payload counting down
  client-side between updates.
- **Help v2**: every troop row shows its movement_diagram; grid scrolls if
  needed; "NEW" badge kept, "SWAP" badge for CT/VA/GO.
- Menu restyle: subtle hex-pattern background, drop shadows under panels,
  bigger title with animated floating pieces, theme button with live preview.

## V2.6 Quiet-start v2

The quiet-start invariant (v1) must hold for EVERY (shape, player count) at
its SHAPE_SIZE, for the DEFAULT army and for every single-swap army
(each of CT/VA/GO in each swappable slot), enforced by tests on a sampled
basis (all defaults exhaustively; swaps: all single swaps for hexagon-6p +
spot checks elsewhere). Sizes found by scripts/search_layouts.py (checked in
under chess3/scripts/).

---

# V3 ADDENDUM

## V3.1 Three more swap troops (engine.py) — SWAP_TROOPS becomes 6

- **JG Juggernaut**: "charges": along each ORTHO ray (max 5 steps) the ONLY
  destinations are (a) the first enemy piece within range (capture) or (b) the
  last EMPTY cell before a blocker / board edge / the 5-step cap. No stopping
  midway on empty cells. Friendly blocker: stops on the cell before it.
- **SN Sniper**: moves 1 DIAG step to EMPTY cells only. Shoots (kind="shoot")
  an enemy at EXACTLY 2 DIAG steps along one diag direction (cell + 2*d),
  ignoring blockers. Cannot target Golems (like all shooters).
- **WD Warden**: moves 1 step in any of the 12 directions (like a King).
  **Protection aura**: a piece standing ORTHO-adjacent to a Warden OWNED BY
  THE SAME PLAYER cannot be captured by kind="move" captures (all movegen must
  exclude such targets). Shoots, bomber explosions, and eliminations bypass
  the aura. Wardens do NOT protect themselves (only neighbors). Implement via
  one helper (e.g. `_protected(victim_cell, victim_owner)`) used by every
  capture-generating path INCLUDING pawn diagonals, cannon jumps, juggernaut
  charges, wizard/valkyrie/knight jumps and slides; king_in_danger inherits it
  automatically via legal_moves.

`SWAP_TROOPS = ("CT","VA","GO","JG","SN","WD")` (each usable at most once;
SWAPPABLE_TYPES unchanged). PIECE_NAMES/PIECE_DESCRIPTIONS gain the 3 types
(same casual tone). PROTOCOL_VERSION bumps to 3 (net.py) since new piece types
cross the wire.

Quiet-start: re-run scripts/search_layouts.py extended to validate ALL 6 swap
troops in every swappable slot at every (shape, count); bump SHAPE_SIZE where
needed (JG's 5-cell charge is the likely stressor). Tests: one movement test
per new troop (JG endpoint-only destinations incl. cap; SN diag shoot over
blocker, not golems; WD aura blocks move-capture but not shoot/explosion, and
does not protect itself), swap validation, TestQuietStart over all 6 swaps.

## V3.2 Presence & invites (net.py) — LAN/VPN only

```python
PRESENCE_PORT = 47734
class PresenceService:
    def __init__(self, my_name: str)
    def start(self)                     # UDP socket, SO_REUSEADDR+SO_BROADCAST
    events: queue.Queue                 # {"t":"invite","from":str,"code":str}
    def peers(self) -> list[dict]       # [{"name","addr","last_seen"}] fresh (<15s)
    def set_name(self, name)
    def set_host_code(self, code|None)  # advertised while hosting
    def invite(self, peer_name: str) -> bool   # unicast invite w/ current code
    def close(self)
```

- Beacon: every 4s broadcast `{"t":"presence","name":...,"iid":...,"hosting":bool}`
  (JSON, one datagram) to 255.255.255.255:PRESENCE_PORT and directed broadcast;
  listen on the same socket; track peers by iid (random per app run, filters
  self-echo). Peers expire after 15s. Malformed datagrams ignored. All
  exception-proof; if the port can't bind, the service degrades to a no-op
  (peers()==[], invite()==False) without raising.
- `invite(peer)` sends `{"t":"invite","from":my_name,"code":host_code}` to the
  peer's address (only meaningful while hosting; returns False if no code).
- Receiving an invite pushes it onto events (the UI shows the Steam-style
  toast). No game-protocol changes.
- Tests: two PresenceService instances on 127.0.0.1 (loopback broadcast may
  not deliver on Windows — in tests inject each other's address directly via a
  test hook or send unicast beacons) see each other, invite flows end to end,
  close() leaks no threads. Keep them timing-tolerant (<10s total).

## V3.3 Theme-aware piece styling (icons.py)

```python
STYLE = {"rim": None, "glow": None, "ink": (25,25,30), "glyph": (245,245,245)}
def set_style(rim=None, glow=None, ink=None, glyph=None)   # partial update
```
draw_piece consults STYLE: `rim` overrides the disc outline color (None =
classic dark), `glow` (None = off) draws a soft 2px halo ring around the disc
before the body, `ink`/`glyph` recolor glyph linework. PLAYER_COLORS stay
untouched (identification!). Cheap — no per-frame surface creation beyond
what's already there. diagrams.py: cache key must include the current style
(or expose diagrams.clear_cache() and call it from main.set_theme).

## V3.4 UI (main.py — mine)

Zoom/pan (wheel zoom 1.0-2.6x toward cursor, middle/right-drag pan, R resets,
auto-reset each new game), selection-scoped red capture tiles for ANY selected
piece (enemy previews are view-only), synthesized sounds via numpy +
pygame.sndarray (turn chime, capture, explosion, shoot, victory, defeat,
invite ping; mixer-failure safe), SETTINGS screen (fullscreen toggle, sound
on/off, volume low/med/high; persisted), theme->icons.set_style wiring +
per-theme piece finishes, FRIENDS screen gains ONLINE (LAN) section with
INVITE buttons while hosting, Steam-style invite toast bottom-right with
ACCEPT/X (auto-join via stored name), presence service runs for the app's
lifetime.

---

# V4 ADDENDUM

## V4.1 Skeletons, bomber fuse, graveyards (engine.py)

- **Piece.uses**: new int field (default 0), counts completed moves for pieces
  that care. Serialization: board rows become [q, r, type, owner, moved, uses]
  — from_dict MUST accept old 5-element rows (uses=0).
- **SK Skeleton** (new type, NOT in armies/swaps): spawned only by the
  Necromancer. Moves/captures exactly like a PAWN of its owner's seat
  (1 forward step, captures on the 3 forward diagonals) but: no double-step,
  NEVER promotes, and after completing its 3rd move it CRUMBLES (removed from
  the board, appended to lost[] as "SK", log "...crumbles to dust"). uses
  increments per completed move (incl. capturing moves). SK may enter
  graveyard cells (see below).
- **NE Necromancer raise v4**: consumes a lost pawn as before but places an
  SK (moved=True, uses=0) instead of a P. Log mentions a skeleton.
- **BM Bomber fuse**: uses increments per completed move; the move that makes
  uses == 10 detonates it at its destination after the move resolves
  (normal explosion rules; log "...fuse runs out"). Explosions from capture
  work as before regardless of count.
- **Graveyards**: GameState gains `graveyards: set[cell]` and
  `graves_left: dict[pid,int]`. On elimination a player gets graves_left = 1.
  New API `apply_grave(pid, cell) -> (ok, err)`: valid iff player is DEAD,
  graves_left>0, cell on board, cell EMPTY and not already a graveyard.
  Effect: cell joins graveyards, decrement graves_left, log
  "NAME curses a tile from beyond the grave". NOT turn-based — dead players
  may do it any time; does not advance the turn.
  Movement rules: NO destination may be a graveyard cell except for SK moves
  and NE "raise" targets (skeletons rise from graves fine). Shoot targets are
  pieces, so skeletons standing on a graveyard can still be shot (no change
  needed). Pieces cannot land there via any move kind, including jumps and
  charges; slides/charges are BLOCKED by graveyard cells (treat like an
  impassable wall for path purposes: a slide ray stops before it; ghost may
  phase THROUGH but not land; wizard/knight/valkyrie jumps simply exclude it).
  to_dict: "graveyards": [[q,r],...], "graves_left": {str(pid): int} (both
  optional on from_dict for back-compat).
- PIECE_NAMES/DESCRIPTIONS gain SK ("Skeleton"), casual voice; note the
  3-move crumble.
- Quiet-start invariant unaffected (no SK/graveyards at start) but re-run the
  suite; extend fuzz so some games include necromancer raises producing SK and
  a mid-game elimination followed by apply_grave.

## V4.2 net.py: grave action + update check; PROTOCOL_VERSION = 4

- New client->server message {"t":"grave","cell":[q,r]} -> apply_grave(pid),
  broadcast state on success (last_move: {"pid": pid, "move": {"from": cell,
  "to": cell, "kind": "grave"}}), error to sender on failure. Host-side
  method HostServer.submit_host_grave(cell).
- PROTOCOL_VERSION = 4 (SK + graveyards cross the wire).
- **Release check helpers** (stdlib urllib, exception-proof):
```python
GITHUB_REPO = "CoopNutt/chess3"
def get_latest_release(timeout=4.0) -> dict|None
    # GET https://api.github.com/repos/{GITHUB_REPO}/releases/latest
    # -> {"tag": "v4.0.0", "url": browser_download_url of the Chess3.exe asset,
    #     "notes": body} or None (no release / no exe asset / any failure)
def download_file(url, dest_path, timeout=30.0) -> bool
    # streams to dest_path, False on any failure (partial file removed)
```
- Tests: grave flow over the wire (eliminate a player via disconnect, submit
  grave, all clients converge; rejected while alive / occupied cell / twice),
  SK serialization roundtrip over the wire, version gate now kicks ver 3.
  get_latest_release/download_file are NOT exercised against real GitHub —
  test only their error paths with an unroutable URL.

## V4.3 icons.py / diagrams.py

- SK glyph: small skull + ribcage hint, matching house style; TYPE_ORDER 21.
- `draw_tombstone(surface, center, size)`: rounded gravestone + cross, for
  graveyard tiles.
- `draw_cracks(surface, points_seed_cell, center, size, color)`: deterministic
  jagged crack polylines (seeded from the cell coords so every client draws
  identical cracks; 2-4 branches, stays inside the hex).
- diagrams: SK demo (forward step + capture diags).

## V4.4 UI v4 (main.py — mine)

Animation profiles per piece type (speed/easing/effects), particle system
(smoke, wind arcs, afterimages, lightning, fire, spawn glow, arrow/cannonball
projectiles, black trail), permanent client-side cracked-tile overlay set fed
by move semantics (JG path, CT/DR/WZ landings, BM blast area, CN target),
graveyard rendering (blacked tile + tombstone), skeleton uses indicator (tiny
pips), dead-player "curse a tile" flow, in-game help filtered to types present
in the match, startup update check with in-app prompt -> download to
Chess3_new.exe -> swap-and-restart via a generated .bat, VERSION constant.

New sounds (sounds.py): grind, slam, lightning, fire, whoosh, cannon, rattle.
