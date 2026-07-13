# CHESS 3

Battle chess for **2–6 players** over the network: 4 board shapes, 14 new
troops, timers, themes, sounds, LAN invites, and lobby-code multiplayer.
Free-for-all — capture a King to eliminate that player. Last one standing wins.

## Play

Run `Chess3.exe` (or `python main.py`).

**Hosting:** click HOST GAME. You'll get two lobby codes:
- **Same-WiFi code** — works for anyone on your network.
- **Internet code** — works from anywhere *if* the auto port-forward succeeded
  (the lobby tells you). If it failed: port-forward TCP 47733 on your router,
  or everyone installs Radmin VPN and friends join with `your-radmin-ip:47733`.

Pick your **match settings** in the lobby (click to change):
- **Map**: Hexagon (2–6p), Octagon (2–6p), Square (2–4p), Triangle (2–3p)
- **Move time**: off / 15s / 30s / 60s / 120s — run out and your turn is skipped
- **Game time**: off / 5 / 10 / 20 / 30 min — when it ends, most troops wins
- **Troop swaps**: swap Catapult / Valkyrie / Golem in for any default troop

Click START GAME once at least 2 players are in.

**Joining:** click JOIN GAME and type the code (recent lobbies get one-click
rejoin buttons). **Friends:** the FRIENDS screen remembers everyone you play
with; star the ones you like.

## The troops

| Troop | Power |
|---|---|
| **Cannon** | Rolls straight; kills by hopping over exactly one piece |
| **Archer** | Snipes enemies exactly 2 tiles away without moving |
| **Wizard** | Teleports anywhere within 2 tiles — walls don't matter |
| **Dragon** | Flies like a Queen, up to 3 tiles |
| **Champion** | Leaps 1–2 straight or 1 diagonal, clean over blockers |
| **Bomber** | Explodes when it captures *or* dies — chain reactions! |
| **Ghost** | Drifts up to 3 tiles diagonally, straight *through* pieces |
| **Necromancer** | Raises your dead pawns back onto the board |
| **Catapult** *(swap-in)* | Hurls boulders at enemies exactly 3 tiles away |
| **Valkyrie** *(swap-in)* | Knight jumps + diagonal slips |
| **Golem** *(swap-in)* | Immune to arrows, boulders and explosions |
| **Juggernaut** *(swap-in)* | Charges up to 5 tiles — hits the first thing in its path |
| **Sniper** *(swap-in)* | Diagonal marksman, shoots 2 tiles over anything |
| **Warden** *(swap-in)* | Protective aura: neighbors can't be captured by moves |

Press **H** anytime — every troop has a movement picture.

## v4 goodies

- **Every troop moves in its own style**: the Juggernaut accelerates with a
  smoke trail, the Wizard phases in with a lightning strike, the Dragon flies
  up and slams down breathing fire, the Champion dashes with afterimages, the
  Valkyrie spins in a whirlwind, ghosts turn translucent... and heavy impacts
  **permanently crack the tiles** they hit.
- **Skeletons**: the Necromancer now raises skeletons — they fight like pawns
  but crumble to dust after 3 moves (watch their little green pips).
- **Bomber fuse**: bombers detonate automatically on their 10th move. Plan
  accordingly.
- **Graveyard curse**: when you're eliminated you get one act of revenge —
  click any empty tile to blacken it with a tombstone. Nothing can ever stand
  there again... except skeletons.
- **Auto-updates**: the game checks GitHub on startup and offers one-click
  update & restart when a new release is out.

## v3 goodies

- **Zoom & pan**: mouse wheel zooms, right/middle-drag pans, **R** resets.
- **Select any piece** (even an enemy's) to preview its moves; everything it
  could capture glows red.
- **Sounds**: your-turn chime, captures, explosions, victory — toggle and
  volume in SETTINGS (plus fullscreen).
- **LAN invites**: friends running Chess 3 on your network (or a shared
  Radmin/Hamachi VPN) show up "online" — hit INVITE while hosting and a
  Steam-style card pops up at their bottom-right with an ACCEPT button.

## Rules quick sheet

- No check or checkmate — you must actually capture the King.
- Lose your King and you're out; your army vanishes. Kings and Golems survive
  explosions.
- On your turn, enemies you can capture glow **red**.
- Pawns step 1 forward (2 on their first move), kill on the 3 forward
  diagonals, auto-promote to Queen on far edges.
- Every start position is machine-verified **quiet** — no first-move snipes,
  on every map shape, even with swaps.
- Disconnect or run out the clock too often and you're skipped/eliminated.
- 5 themes (menu → THEME button): Classic, Midnight, Forest, Ember, Ice.

## Building the exe

```
build.bat
```

Produces `dist\Chess3.exe` — a single file you can send to friends.

## Dev

- Python 3.14 + pygame-ce. `engine.py` (rules) and `net.py` (netcode) have no
  pygame dependency; `diagrams.py` renders the help pictures from real movegen.
- Tests: `python -m unittest discover -s tests -v` (88 tests).
- Board layouts/sizes are machine-searched for quiet starts:
  `python scripts\search_layouts.py`.
