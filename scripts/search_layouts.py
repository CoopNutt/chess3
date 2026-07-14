"""Quiet-start search for board sizes (and per-shape row shifts).

For every shape this script finds, per supported player count, the smallest
board size at which the start position is QUIET:

  * zero placement displacements and all 24*n pieces actually placed,
  * NO capture, shoot, or instant promotion available to ANY player on
    ply 1 -- for the DEFAULT army AND for every single swap: each of the
    swap troops in engine.SWAP_TROOPS (v5: CT/VA/GO/JG/SN/WD/TF/SH/MI)
    substituted into each slot of engine.SWAPPABLE_TYPES (v5: the 8 troop
    slots plus R/N/B/Q).  Ply-1 thief swaps and shaman morphs are fine —
    they are not captures.

If a swap breaks quietness at a size, the size is increased (v3 stressor:
JG's 5-cell ortho charge; the v5 matrix re-searched to identical sizes).
The hexagon layout is fixed (v1 machine-tuned)
and only its sizes may grow.  For the other shapes a small set of row-shift
candidates is also explored; the winner is the (shifts, sizes) combo with
the smallest total size (ties prefer the earlier/default candidate).

Run from anywhere:  python scripts/search_layouts.py
Then bake the printed SHAPE_SIZE / _SHAPE_ROW_SHIFTS values into engine.py.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine
from engine import GameState

SINGLE_SWAPS = [{slot: rep}
                for slot in engine.SWAPPABLE_TYPES
                for rep in engine.SWAP_TROOPS]

# Candidate per-row centering shifts (rows 0..3).  The default v1 tuple
# first; ties in total size go to the earliest candidate.
SHIFT_CANDIDATES = [
    (0, 1, 0, 0),   # v1 hexagon tuning
    (0, 0, 0, 0),
    (0, 1, 0, 1),
    (0, 0, 0, 1),
    (0, 1, 1, 0),
    (0, 0, 1, 0),
    (1, 1, 0, 0),
    (1, 0, 0, 0),
]

# Smallest size where the 8-piece row can even exist (search floor).
MIN_SIZE = {"square": 8, "triangle": 8, "octagon": 10}
MAX_SIZE = 40


def quiet(gs):
    """True if `gs`'s start position is quiet (see module docstring)."""
    if gs.displacements:
        return False
    if len(gs.board) != engine.ARMY_SIZE * len(gs.players):
        return False  # a row was too short: pieces silently dropped
    for p in gs.players:
        pid = p["pid"]
        for mv in gs.all_legal_moves(pid):
            if mv.kind == "shoot":
                return False
            if mv.kind != "move":
                continue
            if mv.to in gs.board:
                return False  # capture available
            if (gs.board[mv.from_].type == "P"
                    and gs._promotes(mv.to, pid)):
                return False  # instant promotion
    return True


def check(shape, n, size, swaps=None):
    try:
        gs = GameState.new_game([(i, "P%d" % i) for i in range(n)],
                                radius=size, shape=shape, swaps=swaps)
    except ValueError:
        return False
    return quiet(gs)


def fully_quiet(shape, n, size):
    """Quiet for the default army and for every single swap."""
    if not check(shape, n, size):
        return False
    return all(check(shape, n, size, sw) for sw in SINGLE_SWAPS)


def min_quiet_size(shape, n, lo):
    for size in range(lo, MAX_SIZE + 1):
        if fully_quiet(shape, n, size):
            return size
    return None


def search_shape(shape):
    counts = sorted(engine._SHAPE_SEATS[shape])
    best = None
    for cand in SHIFT_CANDIDATES:
        engine._SHAPE_ROW_SHIFTS[shape] = cand
        sizes = {}
        lo = MIN_SIZE[shape]
        for n in counts:
            s = min_quiet_size(shape, n, lo)
            if s is None:
                sizes = None
                break
            sizes[n] = s
            lo = max(lo, s)  # boards never shrink as players are added
        if sizes is None:
            print("  shifts %r: NO quiet size <= %d" % (cand, MAX_SIZE))
            continue
        total = sum(sizes.values())
        print("  shifts %r -> sizes %r (total %d)" % (cand, sizes, total))
        if best is None or total < best[0]:
            best = (total, cand, sizes)
    if best is None:
        raise SystemExit("search failed for shape %r" % shape)
    engine._SHAPE_ROW_SHIFTS[shape] = best[1]
    return best[1], best[2]


def search_hexagon():
    """Hexagon layout/shifts are fixed (v1 machine-tuned); only sizes may
    GROW, per count, if a swap troop breaks quietness at the v1 size.

    (Measured for v2: VA's knight jumps reach hex distance 3, so a Valkyrie
    swapped into a row-end slot -- DR, BM or WZ -- reaches the adjacent army
    at radius 11 with 4+ players; 12 breaks the DEFAULT army by parity; 13
    was the first fully quiet v2 size.  v3's JG charges 5 cells straight,
    stressing the sizes further.)
    """
    v1 = {2: 6, 3: 7, 4: 11, 5: 11, 6: 11}
    sizes = {}
    for n, seed in sorted(v1.items()):
        s = min_quiet_size("hexagon", n, seed)
        if s is None:
            raise SystemExit("hexagon n=%d: no quiet size" % n)
        sizes[n] = s
        note = "" if s == seed else "  (GREW from v1 size %d)" % seed
        print("  hexagon n=%d -> size %d%s" % (n, s, note))
    return _SHIFTS_HEX, sizes


_SHIFTS_HEX = (0, 1, 0, 0)


def main():
    t0 = time.time()
    print("Searching hexagon (layout fixed, sizes grow only if needed)...")
    results = {"hexagon": search_hexagon()}
    for shape in ("square", "triangle", "octagon"):
        print("Searching %s..." % shape)
        shifts, sizes = search_shape(shape)
        results[shape] = (shifts, sizes)
        print("  WINNER: shifts %r, sizes %r" % (shifts, sizes))

    print("\n%.1fs. Bake these into engine.py:" % (time.time() - t0))
    print("SHAPE_SIZE = {")
    for shape in ("hexagon", "square", "triangle", "octagon"):
        print('    "%s": %r,' % (shape, results[shape][1]))
    print("}")
    print("_SHAPE_ROW_SHIFTS = {")
    for shape in ("hexagon", "square", "triangle", "octagon"):
        print('    "%s": %r,' % (shape, results[shape][0]))
    print("}")


if __name__ == "__main__":
    main()
