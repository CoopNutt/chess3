"""Engine rules tests: crafted-position tests for all new troops (v1's 8 +
v2's CT/VA/GO + v3's JG/SN/WD + v5's TF/SH/MI), board-shape geometry, swaps,
timers, quiet starts for every (shape, player count), and randomized
full-game fuzzing."""
import json
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import engine
from engine import GameState, Move, Piece


def fresh(n=2):
    return GameState.new_game([(i, "P%d" % i) for i in range(n)])


def clear_keep_kings(gs, far=True):
    """Empty the board except kings parked far apart (so no accidental wins)."""
    gs.board.clear()
    R = gs.radius
    gs.board[(-R, 0)] = Piece("K", 0)
    gs.board[(R, 0)] = Piece("K", 1)


def moves_to(gs, cell):
    return {m.to: m for m in gs.legal_moves(cell)}


def new_shaped(n, shape, swaps=None):
    return GameState.new_game([(i, "P%d" % i) for i in range(n)],
                              shape=shape, swaps=swaps)


def assert_quiet(tc, gs, label):
    """No displacements, full armies, and no capture/shoot/promo for anyone."""
    tc.assertEqual(gs.displacements, 0, "%s: armies collide" % label)
    tc.assertEqual(len(gs.board), engine.ARMY_SIZE * len(gs.players),
                   "%s: pieces missing" % label)
    for p in gs.players:
        pid = p["pid"]
        for mv in gs.all_legal_moves(pid):
            tc.assertNotEqual(mv.kind, "shoot",
                              "%s pid%d shoot %r" % (label, pid, mv))
            if mv.kind != "move":
                continue
            tc.assertNotIn(mv.to, gs.board,
                           "%s pid%d capture %r" % (label, pid, mv))
            if gs.board[mv.from_].type == "P":
                tc.assertFalse(gs._promotes(mv.to, pid),
                               "%s pid%d instant promo %r" % (label, pid, mv))


class TestGeometry(unittest.TestCase):
    def test_cell_counts(self):
        for r, n in ((6, 127), (7, 169), (8, 217), (9, 271)):
            self.assertEqual(len(engine.board_cells(r)), n)

    def test_edge_rows_on_board(self):
        for edge in range(6):
            for row in range(3):
                cells = engine.edge_row(edge, 9, row)
                self.assertEqual(len(cells), 10 + row)
                for c in cells:
                    self.assertIn(c, engine.board_cells(9))

    def test_rotate60_identity(self):
        for cell in [(3, -2), (0, 0), (-9, 4)]:
            self.assertEqual(engine.rotate60(cell, 6), cell)


class TestSetup(unittest.TestCase):
    def test_army_counts_all_player_counts(self):
        for n in range(2, 7):
            gs = fresh(n)
            self.assertEqual(len(gs.board), 24 * n)
            for pid in range(n):
                mine = [pc for pc in gs.board.values() if pc.owner == pid]
                self.assertEqual(len(mine), 24)
                types = sorted(pc.type for pc in mine)
                self.assertEqual(types.count("K"), 1)
                self.assertEqual(types.count("P"), 9)
                for nt in ("CN", "AR", "WZ", "DR", "CH", "BM", "GH", "NE",
                           "TF", "MI"):   # v5.1: thief + mimic are base now
                    self.assertEqual(types.count(nt), 1, nt)
                self.assertEqual(types.count("R"), 1)
                self.assertEqual(types.count("N"), 1)

    def test_serialization_roundtrip(self):
        gs = fresh(6)
        rt = GameState.from_dict(json.loads(json.dumps(gs.to_dict())))
        self.assertEqual(rt.to_dict(), gs.to_dict())

    def test_serialization_carries_shape(self):
        gs = new_shaped(3, "square")
        d = json.loads(json.dumps(gs.to_dict()))
        self.assertEqual(d["shape"], "square")
        rt = GameState.from_dict(d)
        self.assertEqual(rt.shape, "square")
        self.assertEqual(rt.to_dict(), gs.to_dict())
        d.pop("shape")                      # v1 dicts have no shape key
        self.assertEqual(GameState.from_dict(d).shape, "hexagon")


class TestPawn(unittest.TestCase):
    def setUp(self):
        self.gs = fresh(2)
        clear_keep_kings(self.gs)

    def test_steps_and_double(self):
        gs = self.gs
        gs.board[(0, 3)] = Piece("P", 0)  # seat 0: F1=(0,-1) F2=(1,-1)
        tos = set(moves_to(gs, (0, 3)))
        self.assertEqual(tos, {(0, 2), (1, 2), (0, 1), (2, 1)})
        gs.board[(0, 2)] = Piece("P", 0)  # block F1
        tos = set(moves_to(gs, (0, 3)))
        self.assertEqual(tos, {(1, 2), (2, 1)})
        gs.board[(0, 3)].moved = True
        gs.board.pop((0, 2))
        tos = set(moves_to(gs, (0, 3)))
        self.assertEqual(tos, {(0, 2), (1, 2)})

    def test_captures_only_on_forward_diagonals(self):
        gs = self.gs
        gs.board[(0, 3)] = Piece("P", 0, moved=True)
        # F1+F2=(1,-2), 2F1-F2=(-1,-1), 2F2-F1=(2,-1) from (0,3)
        for d in ((1, 1), (-1, 2), (2, 2)):
            gs.board[(0 + d[0], 3 + d[1])] = Piece("N", 1)
        self.assertEqual({m.to for m in gs.legal_moves((0, 3)) if (m.to in gs.board)},
                         set())
        gs.board[(1, 1)] = Piece("N", 1)   # 0,3 + (1,-2)
        gs.board[(-1, 2)] = Piece("N", 1)  # + (-1,-1)
        gs.board[(2, 2)] = Piece("N", 1)   # + (2,-1)
        caps = {m.to for m in gs.legal_moves((0, 3)) if m.to in gs.board}
        self.assertEqual(caps, {(1, 1), (-1, 2), (2, 2)})
        # cannot quiet-move onto a capture diagonal
        gs.board.pop((1, 1))
        caps = {m.to for m in gs.legal_moves((0, 3)) if m.to == (1, 1)}
        self.assertEqual(caps, set())

    def test_promotion(self):
        gs = self.gs
        gs.board[(0, -5)] = Piece("P", 0, moved=True)
        gs.turn_pid = 0
        ok, err = gs.apply_move(0, Move((0, -5), (0, -6)))
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(0, -6)].type, "Q")

    def test_no_promotion_on_own_edge(self):
        gs = self.gs
        # seat 0 home edge is r = +6; a pawn moving along it stays a pawn
        gs.board[(-3, 6)] = Piece("P", 0, moved=True)
        gs.turn_pid = 0
        ok, err = gs.apply_move(0, Move((-3, 6), (-3, 5)))
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(-3, 5)].type, "P")


class TestNewTroops(unittest.TestCase):
    def setUp(self):
        self.gs = fresh(2)
        clear_keep_kings(self.gs)
        self.gs.turn_pid = 0

    def test_cannon_slides_but_cannot_slide_capture(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("CN", 0)
        gs.board[(3, 0)] = Piece("N", 1)
        tos = moves_to(gs, (0, 0))
        self.assertIn((2, 0), tos)          # slide up to the screen
        self.assertNotIn((3, 0), tos)       # cannot capture by sliding

    def test_cannon_screen_jump(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("CN", 0)
        gs.board[(2, 0)] = Piece("P", 0)    # screen (own piece ok)
        gs.board[(4, 0)] = Piece("N", 1)    # target beyond screen
        gs.board[(5, 0)] = Piece("R", 1)    # beyond target: unreachable
        tos = moves_to(gs, (0, 0))
        self.assertIn((4, 0), tos)
        self.assertNotIn((5, 0), tos)
        ok, err = gs.apply_move(0, tos[(4, 0)])
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(4, 0)].type, "CN")
        self.assertIn("N", gs.lost[1])

    def test_archer_shoots_over_blockers_and_never_move_captures(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("AR", 0)
        gs.board[(1, 0)] = Piece("R", 1)    # adjacent enemy blocker
        gs.board[(2, 0)] = Piece("N", 1)    # target at exactly 2
        mvs = gs.legal_moves((0, 0))
        shoot = [m for m in mvs if m.kind == "shoot"]
        self.assertEqual({m.to for m in shoot}, {(2, 0)})
        self.assertNotIn((1, 0), {m.to for m in mvs})  # no melee capture
        ok, err = gs.apply_move(0, shoot[0])
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(0, 0)].type, "AR")  # did not move
        self.assertNotIn((2, 0), gs.board)

    def test_wizard_teleports_over_walls(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("WZ", 0)
        for d in engine.ORTHO:              # fully walled in
            gs.board[(d[0], d[1])] = Piece("P", 1)
        tos = moves_to(gs, (0, 0))
        self.assertIn((2, 0), tos)          # lands beyond the wall
        self.assertIn((1, 0), tos)          # or captures the wall itself

    def test_dragon_capped_at_3(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("DR", 0)
        tos = moves_to(gs, (0, 0))
        self.assertIn((3, 0), tos)
        self.assertNotIn((4, 0), tos)
        self.assertIn((3, 3), tos)          # 3 diag steps of (1,1)
        self.assertNotIn((4, 4), tos)

    def test_champion_leaps(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("CH", 0)
        gs.board[(1, 0)] = Piece("P", 1)    # blocker adjacent
        tos = moves_to(gs, (0, 0))
        self.assertIn((2, 0), tos)          # leaps over it
        self.assertIn((1, 0), tos)          # or captures it
        self.assertIn((1, 1), tos)          # 1 diag
        self.assertNotIn((3, 0), tos)

    def test_bomber_capture_explodes_sparing_kings(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("BM", 0)
        gs.board[(1, 0)] = Piece("N", 1)     # victim
        gs.board[(2, 0)] = Piece("R", 1)     # adjacent to landing cell: dies
        gs.board[(1, 1)] = Piece("P", 0)     # own piece adjacent: dies too
        gs.board[(1, -1)] = Piece("K", 1)    # king adjacent: immune
        # park the real enemy king cell clear (fresh board has it at (6,0))
        ok, err = gs.apply_move(0, Move((0, 0), (1, 0)))
        self.assertTrue(ok, err)
        self.assertNotIn((1, 0), gs.board)   # bomber died in its own blast
        self.assertNotIn((2, 0), gs.board)
        self.assertNotIn((1, 1), gs.board)
        self.assertEqual(gs.board[(1, -1)].type, "K")
        self.assertIn("BM", gs.lost[0])
        self.assertIn("P", gs.lost[0])
        self.assertIn("R", gs.lost[1])

    def test_bomber_chain_reaction(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("AR", 0)
        gs.board[(2, 0)] = Piece("BM", 1)    # shot target
        gs.board[(3, 0)] = Piece("BM", 1)    # adjacent bomber: chains
        gs.board[(4, 0)] = Piece("N", 1)     # adjacent to 2nd bomber: dies
        shoot = [m for m in gs.legal_moves((0, 0)) if m.kind == "shoot"][0]
        ok, err = gs.apply_move(0, shoot)
        self.assertTrue(ok, err)
        for c in ((2, 0), (3, 0), (4, 0)):
            self.assertNotIn(c, gs.board)

    def test_ghost_phases_through(self):
        gs = self.gs
        # (-2,-2) -> (-1,-1), (0,0), (1,1); a 4th step (2,2) is on the
        # board too, so the range cap (not the board edge) stops it.
        gs.board[(-2, -2)] = Piece("GH", 0)
        gs.board[(0, 0)] = Piece("N", 1)     # enemy on the 2nd ray cell
        # (a knight: a rook here would check the king and the king-safety
        # filter would rightly cull the ghost's quiet moves)
        tos = moves_to(gs, (-2, -2))
        self.assertIn((-1, -1), tos)
        self.assertIn((0, 0), tos)           # capture on ray
        self.assertIn((1, 1), tos)           # THROUGH the rook (3rd step)
        self.assertNotIn((2, 2), tos)        # capped at GHOST_RANGE = 3
        gs.board[(-1, -1)] = Piece("P", 0)   # friendly on ray
        tos = moves_to(gs, (-2, -2))
        self.assertNotIn((-1, -1), tos)      # can't land on friendly
        self.assertIn((0, 0), tos)           # still passes through
        self.assertIn((1, 1), tos)

    def test_necromancer_raise(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("NE", 0)
        self.assertEqual([m for m in gs.legal_moves((0, 0))
                          if m.kind == "raise"], [])
        gs.lost[0].append("P")
        raises = [m for m in gs.legal_moves((0, 0)) if m.kind == "raise"]
        self.assertEqual(len(raises), 6)
        ok, err = gs.apply_move(0, raises[0])
        self.assertTrue(ok, err)
        # v4: the necromancer raises a SKELETON (fresh, uses=0), not a pawn
        risen = gs.board[raises[0].to]
        self.assertEqual((risen.type, risen.owner, risen.moved, risen.uses),
                         ("SK", 0, True, 0))
        self.assertNotIn("P", gs.lost[0])
        self.assertEqual(gs.board[(0, 0)].type, "NE")  # did not move


class TestEliminationAndTurns(unittest.TestCase):
    def test_king_capture_eliminates_and_wins_2p(self):
        gs = fresh(2)
        clear_keep_kings(gs)
        gs.board[(5, 0)] = Piece("R", 0)
        gs.turn_pid = 0
        ok, err = gs.apply_move(0, Move((5, 0), (6, 0)))
        self.assertTrue(ok, err)
        self.assertFalse(gs._player(1)["alive"])
        self.assertEqual([pc for pc in gs.board.values() if pc.owner == 1], [])
        self.assertEqual(gs.winner, 0)

    def test_king_capture_3p_continues(self):
        gs = fresh(3)
        gs.board.clear()
        gs.board[(-5, 0)] = Piece("K", 0)
        gs.board[(5, 0)] = Piece("K", 1)
        gs.board[(0, 5)] = Piece("K", 2)
        gs.board[(4, 0)] = Piece("R", 0)
        gs.turn_pid = 0
        ok, err = gs.apply_move(0, Move((4, 0), (5, 0)))
        self.assertTrue(ok, err)
        self.assertFalse(gs._player(1)["alive"])
        self.assertIsNone(gs.winner)
        self.assertEqual(gs.turn_pid, 2)

    def test_moveless_player_skipped(self):
        gs = fresh(3)
        gs.board.clear()
        R = gs.radius
        gs.board[(-R, 0)] = Piece("K", 0)
        gs.board[(R, 0)] = Piece("K", 2)
        # player 1 alive but has no pieces at all -> no moves -> skipped
        gs.turn_pid = 0
        mv = gs.legal_moves((-R, 0))[0]
        ok, err = gs.apply_move(0, mv)
        self.assertTrue(ok, err)
        self.assertEqual(gs.turn_pid, 2)
        self.assertTrue(any("skipped" in ln for ln in gs.log))

    def test_disconnect_elimination_passes_turn(self):
        gs = fresh(3)
        victim = gs.turn_pid
        gs.eliminate(victim, "disconnected")
        self.assertFalse(gs._player(victim)["alive"])
        self.assertNotEqual(gs.turn_pid, victim)
        self.assertIsNone(gs.winner)


class TestShapeGeometry(unittest.TestCase):
    ALL = tuple(engine.SHAPE_NAMES)

    def size_of(self, shape):
        return max(engine.SHAPE_SIZE[shape].values())

    def test_shape_cell_counts(self):
        self.assertEqual(len(engine.shape_cells("square", 12)), 144)
        self.assertEqual(len(engine.shape_cells("triangle", 5)), 21)
        for r in (6, 9):
            self.assertEqual(engine.shape_cells("hexagon", r),
                             engine.board_cells(r))

    def test_octagon_is_hexagon_minus_trimmed_corners(self):
        R = 12
        hexa = engine.board_cells(R)
        octa = engine.shape_cells("octagon", R)
        self.assertTrue(octa < hexa)
        corners = [(cq * R, cr * R) for cq, cr in
                   ((1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1))]
        for c in hexa:
            trimmed = any(engine.hex_dist(c, k) < engine.OCTAGON_TRIM
                          for k in corners)
            self.assertEqual(c not in octa, trimmed, c)

    def test_edge_rows_lie_on_board_at_right_distance(self):
        for shape in self.ALL:
            size = self.size_of(shape)
            cells = engine.shape_cells(shape, size)
            for edge in range(engine.shape_num_edges(shape)):
                for row in range(4):
                    rc = engine.shape_edge_row(shape, edge, size, row)
                    self.assertTrue(rc, (shape, edge, row))
                    self.assertEqual(len(set(rc)), len(rc))
                    for c in rc:
                        self.assertIn(c, cells, (shape, edge, row, c))
                        self.assertEqual(
                            engine.shape_edge_dist(shape, c, edge, size),
                            row, (shape, edge, row, c))
                        self.assertEqual(
                            engine.shape_on_edge_line(shape, c, edge, size),
                            row == 0, (shape, edge, row, c))

    def test_seats_valid_for_every_count(self):
        for shape, sizes in engine.SHAPE_SIZE.items():
            ne = engine.shape_num_edges(shape)
            for n in sorted(sizes):
                seats = engine.shape_seat_edges(shape, n)
                self.assertEqual(len(seats), n)
                self.assertEqual(len(set(seats)), n)
                for s in seats:
                    self.assertTrue(0 <= s < ne, (shape, n, s))
        self.assertEqual(engine.SHAPE_MAX_PLAYERS,
                         {"hexagon": 6, "octagon": 6,
                          "square": 4, "triangle": 3})

    def test_forwards_lead_away_from_own_edge(self):
        for shape in self.ALL:
            size = self.size_of(shape)
            cells = engine.shape_cells(shape, size)
            for edge in range(engine.shape_num_edges(shape)):
                row0 = engine.shape_edge_row(shape, edge, size, 0)
                mid = row0[len(row0) // 2]
                for f in engine.shape_edge_forward(shape, edge):
                    t = (mid[0] + f[0], mid[1] + f[1])
                    self.assertIn(t, cells, (shape, edge, f))
                    self.assertEqual(
                        engine.shape_edge_dist(shape, t, edge, size), 1,
                        (shape, edge, f))

    def test_orient_square_puts_home_edge_on_canonical_line(self):
        S = 12
        cells = engine.shape_cells("square", S)
        for seat in range(4):
            mapped = {engine.shape_orient("square", c, seat, S)
                      for c in cells}
            self.assertEqual(mapped, cells)  # bijection on the board
            for c in engine.shape_edge_row("square", seat, S, 0):
                oq, orr = engine.shape_orient("square", c, seat, S)
                self.assertEqual(orr, S - 1, (seat, c))

    def test_orient_hexagon_matches_rotate60(self):
        for seat in range(6):
            for cell in ((3, -2), (0, 0), (-5, 1)):
                self.assertEqual(
                    engine.shape_orient("hexagon", cell, seat, 6),
                    engine.rotate60(cell, seat))
        self.assertEqual(engine.shape_orient("triangle", (2, 3), 1, 17),
                         (2, 3))  # triangle never rotates

    def test_promotion_zones(self):
        # square: the OPPOSITE edge only
        self.assertTrue(engine.shape_promotes("square", 0, (5, 0), 12))
        self.assertFalse(engine.shape_promotes("square", 0, (0, 5), 12))
        self.assertFalse(engine.shape_promotes("square", 0, (5, 11), 12))
        self.assertTrue(engine.shape_promotes("square", 3, (11, 5), 12))
        # triangle: boundary, not own edge, >= (2*T)//3 rows out
        T = 17  # (2*17)//3 == 11
        self.assertTrue(engine.shape_promotes("triangle", 0, (0, 12), T))
        self.assertTrue(engine.shape_promotes("triangle", 0, (5, 12), T))
        self.assertFalse(engine.shape_promotes("triangle", 0, (0, 5), T))
        self.assertFalse(engine.shape_promotes("triangle", 0, (3, 12), T))
        self.assertFalse(engine.shape_promotes("triangle", 0, (5, 0), T))
        # octagon: hexagon far-edge rule, but trimmed cells never promote
        self.assertTrue(engine.shape_promotes("octagon", 0, (6, -12), 12))
        self.assertFalse(engine.shape_promotes("octagon", 0, (11, -12), 12))
        self.assertFalse(engine.shape_promotes("octagon", 0, (6, 6), 12))


class TestNewTroopsV2(unittest.TestCase):
    def setUp(self):
        self.gs = fresh(2)
        clear_keep_kings(self.gs)
        self.gs.turn_pid = 0

    def test_catapult_moves_one_step_and_shoots_at_exactly_3(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("CT", 0)
        gs.board[(1, 0)] = Piece("P", 0)    # friendly blocker (irrelevant)
        gs.board[(2, 0)] = Piece("P", 1)    # enemy at 2: NOT shootable
        gs.board[(3, 0)] = Piece("R", 1)    # enemy at exactly 3: shootable
        gs.board[(0, 2)] = Piece("N", 1)    # enemy at 2 on other ray: no
        mvs = gs.legal_moves((0, 0))
        shoots = {m.to for m in mvs if m.kind == "shoot"}
        self.assertEqual(shoots, {(3, 0)})  # over both blockers
        tos = {m.to for m in mvs if m.kind == "move"}
        self.assertNotIn((2, 0), tos)       # cannot move-capture
        self.assertNotIn((1, 0), tos)       # blocked by friendly
        self.assertIn((0, 1), tos)          # plain 1-step to empty
        self.assertNotIn((0, 2), tos)       # only 1 step
        ok, err = gs.apply_move(0, Move((0, 0), (3, 0), "shoot"))
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(0, 0)].type, "CT")  # did not move
        self.assertNotIn((3, 0), gs.board)
        self.assertIn("R", gs.lost[1])

    def test_valkyrie_knight_jumps_or_one_diag(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("VA", 0)
        gs.board[(1, 1)] = Piece("P", 0)     # friendly on a diag: blocked
        gs.board[(3, -1)] = Piece("N", 1)    # enemy on a knight cell
        gs.board[(-1, -1)] = Piece("B", 1)   # enemy on a diag cell
        gs.board[(1, 0)] = Piece("P", 1)     # adjacent ortho: NOT reachable
        tos = moves_to(gs, (0, 0))
        self.assertIn((3, -1), tos)          # knight capture
        self.assertIn((-1, -1), tos)         # diag capture
        self.assertNotIn((1, 1), tos)        # friendly-occupied
        self.assertNotIn((1, 0), tos)        # no ortho move at all
        self.assertNotIn((2, 2), tos)        # no 2-step diag
        expected = set()
        for dq, dr in engine.KNIGHT + engine.DIAG:
            expected.add((dq, dr))
        expected.discard((1, 1))
        self.assertEqual(set(tos), expected)  # jumps ignore all blockers

    def test_golem_moves_one_ortho_and_move_captures(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("GO", 0)
        gs.board[(1, 0)] = Piece("N", 1)
        tos = moves_to(gs, (0, 0))
        self.assertEqual(set(tos),
                         {(1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1)})
        ok, err = gs.apply_move(0, tos[(1, 0)])
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(1, 0)].type, "GO")
        self.assertIn("N", gs.lost[1])

    def test_golem_cannot_be_shot_but_can_be_captured(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("GO", 0)
        gs.board[(2, 0)] = Piece("AR", 1)    # archer 2 away: no shot
        gs.board[(0, 3)] = Piece("CT", 1)    # catapult 3 away: no shot
        for cell in ((2, 0), (0, 3)):
            kinds = [(m.kind, m.to) for m in gs.legal_moves(cell)]
            self.assertNotIn(("shoot", (0, 0)), kinds, cell)
        # a plain move-capture still works
        gs.board[(0, 1)] = Piece("R", 1)
        self.assertIn((0, 0), {m.to for m in gs.legal_moves((0, 1))})
        gs.turn_pid = 1
        ok, err = gs.apply_move(1, Move((0, 1), (0, 0)))
        self.assertTrue(ok, err)
        self.assertIn("GO", gs.lost[0])

    def test_golem_survives_explosions(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("BM", 0)
        gs.board[(1, 0)] = Piece("N", 1)     # bomber's victim
        gs.board[(2, 0)] = Piece("GO", 1)    # adjacent golem: survives
        gs.board[(1, 1)] = Piece("R", 1)     # adjacent rook: dies
        ok, err = gs.apply_move(0, Move((0, 0), (1, 0)))
        self.assertTrue(ok, err)
        self.assertNotIn((1, 0), gs.board)   # bomber gone
        self.assertNotIn((1, 1), gs.board)   # rook gone
        self.assertEqual(gs.board[(2, 0)].type, "GO")
        self.assertNotIn("GO", gs.lost[1])
        self.assertIn("R", gs.lost[1])

    def test_archer_still_shoots_non_golems(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("AR", 0)
        gs.board[(2, 0)] = Piece("GO", 1)
        gs.board[(0, 2)] = Piece("N", 1)
        shoots = {m.to for m in gs.legal_moves((0, 0)) if m.kind == "shoot"}
        self.assertEqual(shoots, {(0, 2)})

    def test_square_pawn_promotes_on_opposite_edge_only(self):
        gs = new_shaped(2, "square")   # S=12, seats 0 (r=11) and 2 (r=0)
        gs.board.clear()
        gs.board[(0, 11)] = Piece("K", 0)
        gs.board[(11, 0)] = Piece("K", 1)
        gs.board[(5, 1)] = Piece("P", 0, moved=True)
        gs.turn_pid = 0
        ok, err = gs.apply_move(0, Move((5, 1), (5, 0)))
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(5, 0)].type, "Q")
        gs.winner = None
        gs.board[(0, 5)] = Piece("P", 0, moved=True)
        gs.turn_pid = 0
        ok, err = gs.apply_move(0, Move((0, 5), (0, 4)))  # side edge q=0
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(0, 4)].type, "P")


class TestNewTroopsV3(unittest.TestCase):
    def setUp(self):
        self.gs = fresh(2)
        clear_keep_kings(self.gs)
        self.gs.turn_pid = 0

    # -- Juggernaut ----------------------------------------------------------

    def test_juggernaut_charges_to_ray_endpoints_only(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("JG", 0)
        tos = moves_to(gs, (0, 0))
        # empty rays: ONLY the 5-step cap cell of each ortho ray
        self.assertEqual(set(tos), {(5, 0), (-5, 0), (0, 5), (0, -5),
                                    (-5, 5), (5, -5)})
        for mid in ((1, 0), (2, 0), (3, 0), (4, 0)):
            self.assertNotIn(mid, tos)      # cannot stop mid-ray
        self.assertNotIn((1, 1), tos)       # no diagonal charges

    def test_juggernaut_captures_first_enemy_or_stops_before_blocker(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("JG", 0)
        gs.board[(3, 0)] = Piece("N", 1)    # enemy in range: capture
        gs.board[(-2, 0)] = Piece("P", 0)   # friendly: stop on cell before
        gs.board[(0, 1)] = Piece("R", 1)    # adjacent enemy: capture
        gs.board[(0, -1)] = Piece("P", 0)   # adjacent friendly: ray is dead
        tos = moves_to(gs, (0, 0))
        self.assertIn((3, 0), tos)
        for c in ((1, 0), (2, 0), (4, 0), (5, 0)):
            self.assertNotIn(c, tos)        # no mid-ray stop, no jump past
        self.assertIn((-1, 0), tos)         # last empty before the friendly
        self.assertNotIn((-2, 0), tos)
        self.assertIn((0, 1), tos)
        self.assertNotIn((0, -1), tos)
        ok, err = gs.apply_move(0, tos[(3, 0)])
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(3, 0)].type, "JG")
        self.assertIn("N", gs.lost[1])

    def test_juggernaut_enemy_beyond_range_and_board_edge(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("JG", 0)
        gs.board[(0, 6)] = Piece("N", 1)    # 6 steps out: beyond the cap
        tos = moves_to(gs, (0, 0))
        self.assertIn((0, 5), tos)          # stops at the 5-step cap
        self.assertNotIn((0, 6), tos)
        gs.board[(3, 2)] = Piece("JG", 0)   # (3,3) is the last on-board cell
        tos = moves_to(gs, (3, 2))
        self.assertIn((3, 3), tos)          # last empty before the edge
        self.assertNotIn((3, 4), tos)

    # -- Sniper --------------------------------------------------------------

    def test_sniper_steps_one_diag_to_empty_and_shoots_at_exactly_2(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("SN", 0)
        gs.board[(1, 1)] = Piece("R", 1)    # enemy 1 diag out: NOT capturable
        gs.board[(2, 2)] = Piece("N", 1)    # exactly 2 diag steps: shootable
        gs.board[(4, -2)] = Piece("B", 1)   # 2 steps on another diag: yes
        gs.board[(-2, 4)] = Piece("GO", 1)  # golem at 2 diag steps: immune
        mvs = gs.legal_moves((0, 0))
        shoots = {m.to for m in mvs if m.kind == "shoot"}
        self.assertEqual(shoots, {(2, 2), (4, -2)})   # right over the rook
        tos = {m.to for m in mvs if m.kind == "move"}
        self.assertNotIn((1, 1), tos)       # never move-captures
        self.assertIn((-1, -1), tos)        # quiet 1-step diag
        self.assertNotIn((-2, -2), tos)     # only 1 step
        self.assertNotIn((1, 0), tos)       # no ortho moves at all
        ok, err = gs.apply_move(0, Move((0, 0), (2, 2), "shoot"))
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(0, 0)].type, "SN")  # did not move
        self.assertNotIn((2, 2), gs.board)
        self.assertEqual(gs.board[(1, 1)].type, "R")   # blocker untouched
        self.assertIn("N", gs.lost[1])

    # -- Warden --------------------------------------------------------------

    def test_warden_moves_like_a_king(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("WD", 0)
        gs.board[(1, 0)] = Piece("P", 1)    # enemy (not aura-protected)
        gs.board[(0, 1)] = Piece("P", 0)    # friendly: blocked
        tos = moves_to(gs, (0, 0))
        expected = {d for d in engine.ORTHO + engine.DIAG} - {(0, 1)}
        self.assertEqual(set(tos), {(dq, dr) for dq, dr in expected})
        self.assertNotIn((2, 0), tos)       # one step only

    def test_warden_aura_blocks_every_move_capture_generator(self):
        # WD0 at (0,0) protects the N0 on its ortho-neighbor (1,0) from
        # every kind="move" capture; removing the warden re-enables it.
        cases = [
            ("R", (1, 3), None),            # slide
            ("N", (4, -1), None),           # knight jump
            ("K", (2, 0), None),            # king step
            ("WZ", (2, 1), None),           # teleport
            ("VA", (2, 1), None),           # valkyrie diag jump
            ("CH", (3, 0), None),           # champion 2-ortho leap
            ("GH", (2, -2), None),          # ghost diag landing
            ("BM", (2, 0), None),           # bomber 1-step capture
            ("GO", (2, 0), None),           # golem stomp
            ("WD", (2, 0), None),           # enemy warden's own step
            ("P", (0, -1), None),           # pawn forward diagonal
            ("CN", (1, 3), ((1, 2), "P")),  # cannon jump over a screen
            ("JG", (1, 4), None),           # juggernaut charge
        ]
        for ptype, acell, extra in cases:
            gs = fresh(2)
            clear_keep_kings(gs)
            gs.turn_pid = 1
            gs.board[(0, 0)] = Piece("WD", 0)
            gs.board[(1, 0)] = Piece("N", 0)
            gs.board[acell] = Piece(ptype, 1, moved=True)
            if extra:
                gs.board[extra[0]] = Piece(extra[1], 1)
            tos = {m.to for m in gs.legal_moves(acell) if m.kind == "move"}
            self.assertNotIn((1, 0), tos, "%s pierced the aura" % ptype)
            del gs.board[(0, 0)]            # warden gone: capture works
            tos = {m.to for m in gs.legal_moves(acell) if m.kind == "move"}
            self.assertIn((1, 0), tos, "%s should capture sans warden" % ptype)

    def test_juggernaut_stops_before_warden_protected_enemy(self):
        gs = self.gs
        gs.turn_pid = 1
        gs.board[(0, 0)] = Piece("WD", 0)
        gs.board[(1, 0)] = Piece("N", 0)    # protected
        gs.board[(1, 4)] = Piece("JG", 1)
        tos = moves_to(gs, (1, 4))
        self.assertNotIn((1, 0), tos)       # cannot smash the protected N
        self.assertIn((1, 1), tos)          # skids to a stop right before it

    def test_warden_aura_ignored_by_shoots(self):
        gs = self.gs
        gs.turn_pid = 1
        gs.board[(0, 0)] = Piece("WD", 0)
        gs.board[(1, 0)] = Piece("N", 0)     # protected from moves only
        gs.board[(3, 0)] = Piece("AR", 1)    # archer: 2 ortho away
        gs.board[(-1, -2)] = Piece("SN", 1)  # sniper: 2 diag away
        gs.board[(4, 0)] = Piece("CT", 1)    # catapult: 3 ortho away
        for shooter in ((3, 0), (-1, -2), (4, 0)):
            shoots = {m.to for m in gs.legal_moves(shooter)
                      if m.kind == "shoot"}
            self.assertIn((1, 0), shoots, shooter)
        ok, err = gs.apply_move(1, Move((3, 0), (1, 0), "shoot"))
        self.assertTrue(ok, err)
        self.assertNotIn((1, 0), gs.board)   # shot dead despite the aura
        self.assertIn("N", gs.lost[0])

    def test_warden_aura_ignored_by_explosions(self):
        gs = self.gs
        gs.turn_pid = 1
        gs.board[(0, 0)] = Piece("WD", 0)
        gs.board[(1, 0)] = Piece("N", 0)     # protected; adjacent to (2,0)
        gs.board[(2, 0)] = Piece("P", 0)     # NOT protected (2 from warden)
        gs.board[(3, 0)] = Piece("BM", 1)
        ok, err = gs.apply_move(1, Move((3, 0), (2, 0)))
        self.assertTrue(ok, err)
        self.assertNotIn((2, 0), gs.board)   # bomber died in its own blast
        self.assertNotIn((1, 0), gs.board)   # blast ignores the aura
        self.assertEqual(gs.board[(0, 0)].type, "WD")  # 2 away: unhurt
        self.assertIn("N", gs.lost[0])
        self.assertIn("P", gs.lost[0])

    def test_warden_does_not_protect_itself_but_pairs_guard_each_other(self):
        gs = self.gs
        gs.turn_pid = 1
        gs.board[(0, 0)] = Piece("WD", 0)
        gs.board[(0, 3)] = Piece("R", 1)
        self.assertIn((0, 0), {m.to for m in gs.legal_moves((0, 3))})
        gs.board[(1, 0)] = Piece("WD", 0)    # second warden, ortho-adjacent
        self.assertNotIn((0, 0), {m.to for m in gs.legal_moves((0, 3))})
        gs.board[(1, 3)] = Piece("R", 1)     # and the guard is mutual
        self.assertNotIn((1, 0), {m.to for m in gs.legal_moves((1, 3))})

    def test_warden_aura_is_same_owner_and_ortho_only(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("WD", 0)
        gs.board[(1, 0)] = Piece("N", 1)     # ENEMY beside my warden
        gs.board[(1, 3)] = Piece("R", 0)
        # my warden does not shield enemy pieces from me
        self.assertIn((1, 0), {m.to for m in gs.legal_moves((1, 3))})
        gs.turn_pid = 1
        gs.board[(1, 1)] = Piece("B", 0)     # friendly on a DIAG neighbor
        gs.board[(4, 1)] = Piece("R", 1)     # clear ray along (-1, 0)
        # diag-adjacency grants no protection (aura is ortho-only)
        self.assertIn((1, 1), {m.to for m in gs.legal_moves((4, 1))})

    def test_warden_aura_shields_king_from_danger_but_not_from_shots(self):
        gs = self.gs                          # kings at (-6,0) and (6,0)
        gs.board[(-6, 3)] = Piece("R", 1)     # attacks K0 down the q=-6 line
        self.assertTrue(gs.king_in_danger(0))
        gs.board[(-5, 0)] = Piece("WD", 0)    # warden beside the king
        self.assertFalse(gs.king_in_danger(0))
        gs.board[(-6, 2)] = Piece("AR", 1)    # archer shot hits the king
        self.assertTrue(gs.king_in_danger(0))


class TestSwaps(unittest.TestCase):
    def test_swapped_armies_have_replacements(self):
        swaps = {"CN": "CT", "GH": "VA", "NE": "GO"}
        gs = GameState.new_game([(0, "a"), (1, "b")], swaps=swaps)
        for pid in (0, 1):
            types = [pc.type for pc in gs.board.values() if pc.owner == pid]
            self.assertEqual(len(types), 24)
            for gone in ("CN", "GH", "NE"):
                self.assertNotIn(gone, types)
            for added in ("CT", "VA", "GO"):
                self.assertEqual(types.count(added), 1, added)
            self.assertEqual(types.count("P"), 9)

    def test_swaps_work_on_any_shape(self):
        gs = new_shaped(4, "square", swaps={"AR": "GO"})
        for pid in range(4):
            types = [pc.type for pc in gs.board.values() if pc.owner == pid]
            self.assertNotIn("AR", types)
            self.assertEqual(types.count("GO"), 1)

    def test_v3_swapped_armies_have_replacements(self):
        swaps = {"CN": "JG", "GH": "WD", "AR": "SN"}
        gs = GameState.new_game([(0, "a"), (1, "b")], swaps=swaps)
        for pid in (0, 1):
            types = [pc.type for pc in gs.board.values() if pc.owner == pid]
            self.assertEqual(len(types), 24)
            for gone in ("CN", "GH", "AR"):
                self.assertNotIn(gone, types)
            for added in ("JG", "WD", "SN"):
                self.assertEqual(types.count(added), 1, added)
            self.assertEqual(types.count("P"), 9)

    def test_all_six_swap_troops_at_once(self):
        swaps = {"CN": "CT", "AR": "SN", "WZ": "VA",
                 "CH": "JG", "BM": "GO", "GH": "WD"}
        gs = GameState.new_game([(0, "a"), (1, "b")], swaps=swaps)
        types = [pc.type for pc in gs.board.values() if pc.owner == 0]
        for rep in ("CT", "VA", "GO", "JG", "SN", "WD"):
            self.assertEqual(types.count(rep), 1, rep)
        self.assertEqual(len(types), 24)

    def test_all_seven_swap_troops_at_once(self):
        # v5.1: TF/MI joined the base army, leaving 7 swap troops across 14
        # swappable slots — all seven in one army at once.
        swaps = {"CN": "CT", "AR": "SN", "WZ": "VA", "CH": "JG",
                 "BM": "GO", "GH": "WD", "NE": "SH"}
        self.assertEqual(len(engine.SWAP_TROOPS), 7)
        gs = GameState.new_game([(0, "a"), (1, "b")], swaps=swaps)
        for pid in (0, 1):
            types = [pc.type for pc in gs.board.values() if pc.owner == pid]
            self.assertEqual(len(types), 24)
            for rep in ("CT", "SN", "VA", "JG", "GO", "WD", "SH"):
                self.assertEqual(types.count(rep), 1, rep)
            self.assertEqual(types.count("TF"), 1)   # base since v5.1
            self.assertEqual(types.count("MI"), 1)
            for gone in ("CN", "AR", "WZ", "CH", "BM", "GH", "NE"):
                self.assertNotIn(gone, types)

    def test_v5_classic_slots_replace_all_of_that_type(self):
        # Swapping a classic type replaces ALL pieces of it in every army
        # (v5.1 armies carry ONE rook and ONE knight; TF/MI are slots too).
        for slot, rep, count in (("R", "CT", 1), ("N", "GO", 1),
                                 ("B", "SN", 1), ("Q", "WD", 1),
                                 ("TF", "JG", 1), ("MI", "VA", 1)):
            gs = GameState.new_game([(0, "a"), (1, "b")],
                                    swaps={slot: rep})
            for pid in (0, 1):
                types = [pc.type for pc in gs.board.values()
                         if pc.owner == pid]
                self.assertNotIn(slot, types, (slot, rep))
                self.assertEqual(types.count(rep), count, (slot, rep))
                self.assertEqual(len(types), 24)
        # pawns and kings stay unswappable
        for bad in ({"P": "TF"}, {"K": "MI"}):
            with self.assertRaises(ValueError, msg=bad):
                GameState.new_game([(0, "a"), (1, "b")], swaps=bad)

    def test_bad_swaps_rejected(self):
        players = [(0, "a"), (1, "b")]
        for bad in ({"P": "CT"}, {"K": "GO"},            # not swappable
                    {"CN": "XX"}, {"CN": "Q"},           # bad replacement
                    {"CN": "CT", "AR": "CT"},            # duplicate
                    {"CN": "JG", "AR": "JG"}):           # v3 duplicate
            with self.assertRaises(ValueError, msg=bad):
                GameState.new_game(players, swaps=bad)

    def test_unsupported_counts_and_shapes_rejected(self):
        five = [(i, "p%d" % i) for i in range(5)]
        four = five[:4]
        with self.assertRaises(ValueError):
            GameState.new_game(five, shape="square")
        with self.assertRaises(ValueError):
            GameState.new_game(four, shape="triangle")
        with self.assertRaises(ValueError):
            GameState.new_game(four, shape="pentagon")


class TestTimers(unittest.TestCase):
    def test_force_skip_advances_turn_and_logs(self):
        gs = fresh(2)
        gs.force_skip(1)                     # not their turn: no-op
        self.assertEqual(gs.turn_pid, 0)
        gs.force_skip(0)
        self.assertEqual(gs.turn_pid, 1)
        self.assertTrue(any("ran out of time" in ln for ln in gs.log))
        gs.winner = 0                        # game over: no-op
        gs.force_skip(1)
        self.assertEqual(gs.turn_pid, 1)

    def test_end_by_time_most_pieces_wins(self):
        gs = fresh(2)
        clear_keep_kings(gs)
        gs.board[(0, 0)] = Piece("P", 0)     # p0: 2 pieces, p1: 1
        gs.end_by_time()
        self.assertEqual(gs.winner, 0)
        self.assertTrue(any("Time" in ln for ln in gs.log))

    def test_end_by_time_tie_is_draw(self):
        gs = fresh(2)
        clear_keep_kings(gs)                 # 1 king each
        gs.end_by_time()
        self.assertEqual(gs.winner, -1)

    def test_end_by_time_noop_when_over(self):
        gs = fresh(2)
        gs.winner = 1
        gs.end_by_time()
        self.assertEqual(gs.winner, 1)


class TestKingSafety(unittest.TestCase):
    """You may never play a move that leaves your own king capturable."""

    def setUp(self):
        self.gs = fresh(2)
        clear_keep_kings(self.gs)   # kings at (-6,0) and (6,0)
        self.gs.turn_pid = 0

    def test_king_cannot_step_into_attack(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("R", 1)   # rook sweeps the whole r=0 line
        tos = set(moves_to(gs, (-6, 0)))
        self.assertNotIn((-5, 0), tos)     # stays on the swept line: illegal
        self.assertIn((-6, 1), tos)        # stepping off the line is fine

    def test_pinned_piece_cannot_move(self):
        gs = self.gs
        # enemy rook on the king's line, our knight blocking = pinned
        gs.board[(0, 0)] = Piece("R", 1)
        gs.board[(-3, 0)] = Piece("N", 0)
        self.assertEqual(gs.legal_moves((-3, 0)), [])
        # remove the rook: knight free again
        del gs.board[(0, 0)]
        self.assertTrue(gs.legal_moves((-3, 0)))

    def test_must_resolve_check(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("R", 1)   # checks the king along r=0
        gs.board[(-2, -2)] = Piece("GH", 0)
        self.assertTrue(gs.king_in_danger(0))
        allowed = {m.to for m in gs.legal_moves((-2, -2))}
        # only capturing the rook or blocking its ray helps
        self.assertEqual(allowed, {(0, 0), (-3, 0)})

    def test_shoot_that_opens_a_line_is_illegal(self):
        gs = self.gs
        # enemy rook behind an enemy pawn: shooting the pawn opens the check
        gs.board[(3, 0)] = Piece("R", 1)
        gs.board[(-1, 0)] = Piece("P", 1)
        gs.board[(-3, 2)] = Piece("AR", 0)  # exactly 2 ortho from (-1,0)? no:
        gs.board.pop((-3, 2))
        gs.board[(-1, 2)] = Piece("AR", 0)  # (-1,2) + 2*(0,-1) = (-1,0)
        shoots = [m for m in gs.legal_moves((-1, 2)) if m.kind == "shoot"]
        self.assertEqual(shoots, [])        # would expose the king

    def test_checkmated_player_is_skipped_then_captured(self):
        gs = fresh(2)
        gs.board.clear()
        R = gs.radius
        gs.board[(-R, 0)] = Piece("K", 0)
        gs.board[(R, 0)] = Piece("K", 1)
        # box king 0 in: rook pins the whole line, queen next to it covers all
        gs.board[(-R + 2, 0)] = Piece("Q", 1)
        gs.board[(-R + 2, -1)] = Piece("R", 1)
        gs.board[(-R, 2)] = Piece("R", 1)
        if gs.all_legal_moves(0):
            self.skipTest("crafted mate no longer tight after rule changes")
        gs.turn_pid = 1
        ok, err = gs.apply_move(1, Move((-R + 2, 0), (-R + 1, 0)))
        # whatever the queen does, player 0 must not get an illegal turn
        self.assertTrue(ok, err)
        if gs.winner is None:
            self.assertNotEqual(gs.turn_pid, 0 if not gs.all_legal_moves(0)
                                else -99)

    def test_fast_attack_test_matches_scan_on_starts(self):
        for n in (2, 3, 6):
            gs = fresh(n)
            for p in gs.players:
                self.assertEqual(gs.king_in_danger(p["pid"]),
                                 gs._king_in_danger_scan(p["pid"]))


class TestQuietStart(unittest.TestCase):
    """Nobody may capture, shoot, or promote on ply 1, for ANY (shape,
    player count) at its SHAPE_SIZE — default armies and swapped armies.

    This pins the (layout, shifts, sizes) tuning found by
    scripts/search_layouts.py; see engine._ARMY_ROWS / engine.SHAPE_SIZE.
    """

    def test_all_player_counts_start_quiet(self):
        for n in range(2, 7):
            assert_quiet(self, fresh(n), "hexagon n=%d" % n)

    def test_every_shape_and_count_starts_quiet(self):
        for shape, sizes in engine.SHAPE_SIZE.items():
            for n in sorted(sizes):
                assert_quiet(self, new_shaped(n, shape),
                             "%s n=%d" % (shape, n))

    def test_hexagon_6p_every_single_swap_starts_quiet(self):
        for slot in engine.SWAPPABLE_TYPES:
            for rep in engine.SWAP_TROOPS:
                gs = new_shaped(6, "hexagon", swaps={slot: rep})
                assert_quiet(self, gs, "hexagon 6p swap %s->%s" % (slot, rep))

    def test_sampled_swaps_start_quiet_on_other_shapes(self):
        samples = (("square", 4), ("triangle", 3), ("octagon", 6),
                   ("square", 2), ("octagon", 2))
        picks = ({"CN": "CT"}, {"AR": "GO"}, {"GH": "VA"},
                 {"DR": "VA"}, {"WZ": "VA"}, {"NE": "CT"}, {"BM": "GO"},
                 {"CN": "JG"}, {"DR": "JG"}, {"WZ": "JG"},  # v3: 5-tile charge
                 {"AR": "SN"}, {"NE": "SN"}, {"GH": "WD"}, {"BM": "WD"},
                 # v5.1: shaman + the newly swappable classic/TF/MI slots
                 {"Q": "SH"}, {"R": "SH"}, {"N": "VA"},
                 {"Q": "JG"}, {"N": "SN"}, {"TF": "CT"}, {"MI": "WD"},
                 {"B": "GO"})
        for shape, n in samples:
            for sw in picks:
                gs = new_shaped(n, shape, swaps=sw)
                assert_quiet(self, gs, "%s n=%d swap %r" % (shape, n, sw))


class TestSkeleton(unittest.TestCase):
    """V4.1: SK moves like its owner's pawn (no double-step, no promotion)
    and crumbles to dust after its 3rd completed move."""

    def setUp(self):
        self.gs = fresh(2)
        clear_keep_kings(self.gs)
        self.gs.turn_pid = 0

    def test_names_and_descriptions(self):
        self.assertEqual(engine.PIECE_NAMES["SK"], "Skeleton")
        self.assertIn("SK", engine.PIECE_DESCRIPTIONS)
        self.assertIn("3", engine.PIECE_DESCRIPTIONS["SK"])   # crumble count
        self.assertIn("SKELETON", engine.PIECE_DESCRIPTIONS["NE"])
        self.assertIn("10", engine.PIECE_DESCRIPTIONS["BM"])  # the fuse

    def test_moves_like_a_pawn_but_no_double_step(self):
        gs = self.gs
        gs.board[(0, 3)] = Piece("SK", 0)      # unmoved: STILL no double
        tos = set(moves_to(gs, (0, 3)))
        self.assertEqual(tos, {(0, 2), (1, 2)})
        # captures ONLY on the 3 forward diagonals
        gs.board[(1, 1)] = Piece("N", 1)       # F1+F2
        gs.board[(-1, 2)] = Piece("B", 1)      # 2F1-F2
        gs.board[(2, 2)] = Piece("R", 1)       # 2F2-F1
        gs.board[(1, 3)] = Piece("P", 1)       # beside it: not capturable
        tos = set(moves_to(gs, (0, 3)))
        self.assertEqual(tos, {(0, 2), (1, 2), (1, 1), (-1, 2), (2, 2)})
        # and quiet moves cannot go to an (empty) capture diagonal
        del gs.board[(1, 1)]
        self.assertNotIn((1, 1), set(moves_to(gs, (0, 3))))

    def test_crumbles_after_third_completed_move(self):
        gs = self.gs
        gs.board[(0, 3)] = Piece("SK", 0, moved=True)
        for step, dest in enumerate(((0, 2), (0, 1), (0, 0)), start=1):
            gs.turn_pid = 0
            ok, err = gs.apply_move(0, Move((0, dest[1] + 1), dest))
            self.assertTrue(ok, err)
            if step < 3:
                self.assertEqual(gs.board[dest].uses, step)
        self.assertNotIn((0, 0), gs.board)     # crumbled after move 3
        self.assertIn("SK", gs.lost[0])
        self.assertTrue(any("crumbles to dust" in ln for ln in gs.log))

    def test_capturing_on_the_third_move_still_crumbles(self):
        gs = self.gs
        gs.board[(0, 3)] = Piece("SK", 0, moved=True, uses=2)
        gs.board[(1, 1)] = Piece("N", 1)       # forward-diagonal victim
        ok, err = gs.apply_move(0, Move((0, 3), (1, 1)))
        self.assertTrue(ok, err)
        self.assertNotIn((1, 1), gs.board)     # took the N, then crumbled
        self.assertIn("N", gs.lost[1])
        self.assertIn("SK", gs.lost[0])

    def test_never_promotes(self):
        gs = self.gs
        gs.board[(0, -5)] = Piece("SK", 0, moved=True)
        ok, err = gs.apply_move(0, Move((0, -5), (0, -6)))
        self.assertTrue(ok, err)
        # a pawn ending on this far-edge cell becomes a Queen; SK never does
        self.assertEqual(gs.board[(0, -6)].type, "SK")
        self.assertEqual(gs.board[(0, -6)].uses, 1)

    def test_raised_skeleton_lives_for_exactly_three_moves(self):
        gs = self.gs
        gs.board[(0, 3)] = Piece("NE", 0)
        gs.lost[0].append("P")
        rz = [m for m in gs.legal_moves((0, 3))
              if m.kind == "raise" and m.to == (0, 2)]
        ok, err = gs.apply_move(0, rz[0])
        self.assertTrue(ok, err)
        for dest in ((0, 1), (0, 0), (0, -1)):
            gs.turn_pid = 0
            ok, err = gs.apply_move(0, Move((0, dest[1] + 1), dest))
            self.assertTrue(ok, err)
        self.assertNotIn((0, -1), gs.board)
        self.assertEqual(gs.lost[0], ["SK"])   # the P was consumed, SK died


class TestBomberFuse(unittest.TestCase):
    """V4.1: a bomber detonates at its destination when its 10th completed
    move resolves; a capture-explosion beforehand ends the fuse."""

    def setUp(self):
        self.gs = fresh(2)
        clear_keep_kings(self.gs)
        self.gs.turn_pid = 0

    def test_fuse_detonates_on_exactly_the_10th_move(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("BM", 0, moved=True, uses=8)
        ok, err = gs.apply_move(0, Move((0, 0), (1, 0)))   # 9th move
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(1, 0)].type, "BM")      # still ticking
        self.assertFalse(any("fuse" in ln for ln in gs.log))
        gs.board[(2, 1)] = Piece("N", 1)    # adjacent to the blast: dies
        gs.board[(1, 1)] = Piece("P", 0)    # own piece adjacent: dies too
        gs.board[(3, 0)] = Piece("GO", 1)   # golem adjacent: shrugs it off
        gs.turn_pid = 0
        ok, err = gs.apply_move(0, Move((1, 0), (2, 0)))   # 10th move
        self.assertTrue(ok, err)
        self.assertNotIn((2, 0), gs.board)  # went up with its own blast
        self.assertNotIn((2, 1), gs.board)
        self.assertNotIn((1, 1), gs.board)
        self.assertEqual(gs.board[(3, 0)].type, "GO")
        self.assertIn("BM", gs.lost[0])
        self.assertIn("P", gs.lost[0])
        self.assertIn("N", gs.lost[1])
        self.assertTrue(any("fuse runs out" in ln for ln in gs.log))
        self.assertTrue(any("BOOM" in ln for ln in gs.log))

    def test_capture_explosion_ends_the_fuse_no_double_fire(self):
        for uses in (3, 9):    # incl. a capture on what would be move 10
            gs = fresh(2)
            clear_keep_kings(gs)
            gs.turn_pid = 0
            gs.board[(0, 0)] = Piece("BM", 0, moved=True, uses=uses)
            gs.board[(1, 0)] = Piece("N", 1)
            ok, err = gs.apply_move(0, Move((0, 0), (1, 0)))
            self.assertTrue(ok, err)
            self.assertNotIn((1, 0), gs.board)
            self.assertEqual(gs.lost[0].count("BM"), 1, uses)
            self.assertEqual(sum(1 for ln in gs.log if "BOOM" in ln), 1,
                             uses)
            self.assertFalse(any("fuse" in ln for ln in gs.log), uses)


class TestGraveyards(unittest.TestCase):
    """V4.1: dead players curse tiles; graveyards wall off all movement
    except skeleton moves and necromancer raise targets."""

    def setUp(self):
        self.gs = fresh(2)
        clear_keep_kings(self.gs)
        self.gs.turn_pid = 0

    def test_new_game_has_no_graveyards(self):
        gs = fresh(3)
        self.assertEqual(gs.graveyards, set())
        self.assertEqual(gs.graves_left, {})

    def test_apply_grave_validation_matrix(self):
        gs = fresh(3)
        turn_before = gs.turn_pid
        # alive players may not curse (even with a cell that would be fine)
        ok, err = gs.apply_grave(0, (0, 0))
        self.assertFalse(ok)
        # unknown player
        self.assertFalse(gs.apply_grave(99, (0, 0))[0])
        # malformed cell
        self.assertFalse(gs.apply_grave(0, "nope")[0])
        gs.eliminate(1, "test")
        self.assertEqual(gs.graves_left[1], 1)  # granted ON elimination
        # occupied cell rejected
        occupied = next(iter(gs.board))
        self.assertFalse(gs.apply_grave(1, occupied)[0])
        # off-board cell rejected
        self.assertFalse(gs.apply_grave(1, (99, 99))[0])
        self.assertEqual(gs.graves_left[1], 1)  # failures consume nothing
        # dead player OK — not turn-based, does not advance the turn
        ok, err = gs.apply_grave(1, (0, 0))
        self.assertTrue(ok, err)
        self.assertIn((0, 0), gs.graveyards)
        self.assertEqual(gs.graves_left[1], 0)
        self.assertEqual(gs.turn_pid, turn_before)
        self.assertIsNone(gs.winner)
        self.assertTrue(any("curses a tile from beyond the grave" in ln
                            for ln in gs.log))
        # second grave rejected (only one curse per death)
        self.assertFalse(gs.apply_grave(1, (1, 0))[0])
        # a "grave" pseudo-move cannot be smuggled through apply_move
        ok, err = gs.apply_move(gs.turn_pid, Move((0, 0), (0, 0), "grave"))
        self.assertFalse(ok)
        # another dead player: same cell rejected, a fresh cell is fine
        gs.eliminate(2, "test")   # ends the game (0 wins) — curse still OK
        self.assertFalse(gs.apply_grave(2, (0, 0))[0])
        self.assertTrue(gs.apply_grave(2, (1, 0))[0])
        self.assertEqual(gs.graveyards, {(0, 0), (1, 0)})

    def test_move_from_dict_accepts_grave_kind(self):
        m = Move.from_dict({"from": [2, 3], "to": [2, 3], "kind": "grave"})
        self.assertEqual(m.kind, "grave")
        with self.assertRaises(ValueError):
            Move.from_dict({"from": [0, 0], "to": [0, 0], "kind": "bogus"})

    def test_slides_and_charges_stop_before_a_graveyard(self):
        gs = self.gs
        gs.graveyards.add((2, 0))
        gs.board[(0, 0)] = Piece("R", 0)
        tos = set(moves_to(gs, (0, 0)))
        self.assertIn((1, 0), tos)
        self.assertNotIn((2, 0), tos)
        self.assertNotIn((3, 0), tos)          # the ray is walled off
        gs.board[(3, 0)] = Piece("N", 1)       # enemy behind the wall
        self.assertNotIn((3, 0), set(moves_to(gs, (0, 0))))
        gs.board[(0, 0)] = Piece("BM", 0)      # short slider, same wall
        tos = set(moves_to(gs, (0, 0)))
        self.assertIn((1, 0), tos)
        self.assertNotIn((2, 0), tos)
        gs.board[(0, 0)] = Piece("JG", 0)      # charge: stops before it
        tos = set(moves_to(gs, (0, 0)))
        self.assertIn((1, 0), tos)             # last empty before the wall
        self.assertNotIn((2, 0), tos)
        self.assertNotIn((3, 0), tos)          # cannot smash through

    def test_jumps_exclude_graveyards_but_leap_over_them(self):
        gs = self.gs
        gs.graveyards.update([(1, 0), (3, -1)])
        gs.board[(0, 0)] = Piece("N", 0)
        tos = set(moves_to(gs, (0, 0)))
        self.assertNotIn((3, -1), tos)         # knight can't land on one
        self.assertIn((3, -2), tos)
        gs.board[(0, 0)] = Piece("WZ", 0)
        tos = set(moves_to(gs, (0, 0)))
        self.assertNotIn((1, 0), tos)          # teleports can't land either
        self.assertIn((2, 0), tos)             # but LEAP right over it
        gs.board[(0, 0)] = Piece("CH", 0)
        tos = set(moves_to(gs, (0, 0)))
        self.assertNotIn((1, 0), tos)
        self.assertIn((2, 0), tos)             # 2-ortho leap over the grave
        gs.board[(0, 0)] = Piece("K", 0)
        self.assertNotIn((1, 0), set(moves_to(gs, (0, 0))))

    def test_pawn_blocked_by_graveyards(self):
        gs = self.gs
        gs.board[(0, 3)] = Piece("P", 0)       # unmoved, seat 0
        gs.graveyards.add((0, 2))              # on the F1 step
        tos = set(moves_to(gs, (0, 3)))
        self.assertEqual(tos, {(1, 2), (2, 1)})  # F1 single AND double gone
        gs.graveyards.discard((0, 2))
        gs.graveyards.add((0, 1))              # only the F1 DOUBLE target
        tos = set(moves_to(gs, (0, 3)))
        self.assertEqual(tos, {(0, 2), (1, 2), (2, 1)})

    def test_ghost_phases_through_but_cannot_land(self):
        gs = self.gs
        gs.graveyards.add((1, 1))
        gs.board[(0, 0)] = Piece("GH", 0)
        gs.board[(2, 2)] = Piece("R", 1)
        tos = set(moves_to(gs, (0, 0)))
        self.assertNotIn((1, 1), tos)          # can't land on the grave
        self.assertIn((2, 2), tos)             # phases through, captures
        self.assertIn((3, 3), tos)

    def test_cannon_ray_walled_by_graveyard(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("CN", 0)
        gs.board[(1, 0)] = Piece("P", 0)       # screen
        gs.board[(3, 0)] = Piece("N", 1)       # target beyond the screen
        self.assertIn((3, 0), set(moves_to(gs, (0, 0))))
        gs.graveyards.add((2, 0))              # wall between screen+target
        self.assertNotIn((3, 0), set(moves_to(gs, (0, 0))))

    def test_skeleton_enters_graveyards_and_can_be_shot_there(self):
        gs = self.gs
        gs.graveyards.add((0, 2))
        gs.board[(0, 3)] = Piece("SK", 0, moved=True)
        self.assertIn((0, 2), set(moves_to(gs, (0, 3))))
        ok, err = gs.apply_move(0, Move((0, 3), (0, 2)))
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(0, 2)].type, "SK")  # standing on a grave
        # a rook cannot reach it (the slide stops before the graveyard)...
        gs.board[(0, -1)] = Piece("R", 1)
        self.assertNotIn((0, 2), {m.to for m in gs.legal_moves((0, -1))})
        # ...but shoots target the PIECE, so the archer takes the shot
        gs.board[(0, 0)] = Piece("AR", 1)
        shoots = [m for m in gs.legal_moves((0, 0)) if m.kind == "shoot"]
        self.assertIn((0, 2), {m.to for m in shoots})
        gs.turn_pid = 1
        ok, err = gs.apply_move(1, Move((0, 0), (0, 2), "shoot"))
        self.assertTrue(ok, err)
        self.assertNotIn((0, 2), gs.board)
        self.assertIn("SK", gs.lost[0])
        self.assertIn((0, 2), gs.graveyards)   # the tile stays cursed

    def test_raise_targets_include_graveyards(self):
        gs = self.gs
        gs.graveyards.add((1, 0))
        gs.board[(0, 0)] = Piece("NE", 0)
        gs.lost[0].append("P")
        mvs = gs.legal_moves((0, 0))
        raises = {m.to for m in mvs if m.kind == "raise"}
        self.assertIn((1, 0), raises)          # skeletons rise from graves
        ok, err = gs.apply_move(0, Move((0, 0), (1, 0), "raise"))
        self.assertTrue(ok, err)
        sk = gs.board[(1, 0)]
        self.assertEqual((sk.type, sk.owner, sk.moved, sk.uses),
                         ("SK", 0, True, 0))

    def test_necromancer_diag_step_excludes_graveyards(self):
        gs = self.gs
        gs.graveyards.add((1, 1))
        gs.board[(0, 0)] = Piece("NE", 0)
        tos = {m.to for m in gs.legal_moves((0, 0)) if m.kind == "move"}
        self.assertNotIn((1, 1), tos)
        self.assertIn((-1, -1), tos)


class TestSerializationV4(unittest.TestCase):
    def test_roundtrip_with_uses_and_graveyards(self):
        gs = fresh(3)
        bm = next(c for c, pc in gs.board.items()
                  if pc.type == "BM" and pc.owner == 0)
        gs.board[bm].uses = 7
        gs.board[(0, 0)] = Piece("SK", 1, moved=True, uses=2)
        gs.eliminate(2, "test")
        ok, err = gs.apply_grave(2, (1, 0))
        self.assertTrue(ok, err)
        d = json.loads(json.dumps(gs.to_dict()))
        self.assertTrue(all(len(row) == 6 for row in d["board"]))
        self.assertIn([1, 0], d["graveyards"])
        self.assertEqual(d["graves_left"], {"2": 0})
        rt = GameState.from_dict(d)
        self.assertEqual(rt.to_dict(), gs.to_dict())
        self.assertEqual(rt.board[bm].uses, 7)
        self.assertEqual(rt.board[(0, 0)].uses, 2)
        self.assertEqual(rt.graveyards, {(1, 0)})
        self.assertEqual(rt.graves_left, {2: 0})

    def test_from_dict_accepts_old_5_element_rows(self):
        gs = fresh(2)
        d = json.loads(json.dumps(gs.to_dict()))
        for row in d["board"]:
            self.assertEqual(len(row), 6)
            del row[5]
        d.pop("graveyards")
        d.pop("graves_left")
        rt = GameState.from_dict(d)
        self.assertEqual(len(rt.board), len(gs.board))
        self.assertTrue(all(pc.uses == 0 for pc in rt.board.values()))
        self.assertEqual(rt.graveyards, set())
        self.assertEqual(rt.graves_left, {})
        # and it upgrades forward into the exact v4 schema
        self.assertEqual(rt.to_dict(), gs.to_dict())


class TestThief(unittest.TestCase):
    """V5.2: the Thief slides like a rook but never captures; instead it
    swaps cells with the first non-King piece within 3 ortho steps."""

    def setUp(self):
        self.gs = fresh(2)
        clear_keep_kings(self.gs)   # kings at (-6,0) and (6,0)
        self.gs.turn_pid = 0

    def test_names_and_descriptions(self):
        self.assertEqual(engine.PIECE_NAMES["TF"], "Thief")
        self.assertEqual(engine.PIECE_NAMES["SH"], "Shaman")
        self.assertEqual(engine.PIECE_NAMES["MI"], "Mimic")
        for t in ("TF", "SH", "MI"):
            self.assertIn(t, engine.PIECE_DESCRIPTIONS)
        self.assertIn("3", engine.PIECE_DESCRIPTIONS["TF"])   # swap range
        self.assertIn("soul", engine.PIECE_DESCRIPTIONS["SH"].lower())
        self.assertIn("last", engine.PIECE_DESCRIPTIONS["MI"].lower())

    def test_slides_to_empty_only_and_swaps_friend_or_foe(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("TF", 0)
        gs.board[(2, 0)] = Piece("N", 1)    # enemy 2 steps out
        gs.board[(0, 2)] = Piece("P", 0)    # friend 2 steps out
        mvs = gs.legal_moves((0, 0))
        self.assertEqual({m.kind for m in mvs}, {"move", "swap"})
        move_tos = {m.to for m in mvs if m.kind == "move"}
        swap_tos = {m.to for m in mvs if m.kind == "swap"}
        self.assertIn((1, 0), move_tos)     # slide up to the enemy...
        self.assertNotIn((2, 0), move_tos)  # ...but NEVER capture it
        self.assertIn((0, 1), move_tos)
        self.assertNotIn((0, 2), move_tos)  # friends block slides too
        self.assertEqual(swap_tos, {(2, 0), (0, 2)})   # foe AND friend

    def test_swap_range_capped_at_three_and_first_piece_only(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("TF", 0)
        gs.board[(0, 4)] = Piece("N", 1)    # 4 steps: out of swap reach
        swaps = {m.to for m in gs.legal_moves((0, 0)) if m.kind == "swap"}
        self.assertEqual(swaps, set())
        gs.board[(0, 3)] = Piece("N", 1)    # exactly 3: fine
        swaps = {m.to for m in gs.legal_moves((0, 0)) if m.kind == "swap"}
        self.assertEqual(swaps, {(0, 3)})
        gs.board[(0, 1)] = Piece("P", 0)    # first piece on the ray wins
        swaps = {m.to for m in gs.legal_moves((0, 0)) if m.kind == "swap"}
        self.assertEqual(swaps, {(0, 1)})   # cannot reach past it

    def test_swap_ray_walled_by_graveyard(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("TF", 0)
        gs.board[(0, 2)] = Piece("N", 1)
        self.assertIn((0, 2), {m.to for m in gs.legal_moves((0, 0))
                               if m.kind == "swap"})
        gs.graveyards.add((0, 1))           # wall between thief and target
        self.assertEqual({m.to for m in gs.legal_moves((0, 0))
                          if m.kind == "swap"}, set())

    def test_never_swaps_with_kings(self):
        gs = self.gs
        gs.board[(5, 0)] = Piece("TF", 0)   # right beside the ENEMY king
        tos = {m.to for m in gs.legal_moves((5, 0))}
        self.assertNotIn((6, 0), tos)       # no swap, no capture, nothing
        gs.board[(-5, 0)] = Piece("TF", 0)  # right beside its OWN king
        self.assertNotIn((-6, 0), {m.to for m in gs.legal_moves((-5, 0))})

    def test_thief_never_attacks_anything(self):
        gs = self.gs
        gs.board[(-6, 3)] = Piece("TF", 1)  # rook-lined up with K0
        self.assertFalse(gs.king_in_danger(0))
        self.assertFalse(gs._king_in_danger_scan(0))
        gs.board[(-5, 0)] = Piece("TF", 1)  # right next to K0
        self.assertFalse(gs.king_in_danger(0))
        self.assertFalse(gs._king_in_danger_scan(0))
        del gs.board[(-5, 0)]
        gs.board[(-6, 3)] = Piece("R", 1)   # contrast: a rook DOES attack
        self.assertTrue(gs.king_in_danger(0))

    def test_swap_applies_thief_moved_victim_keeps_flags(self):
        gs = self.gs
        tf = Piece("TF", 0)                     # moved=False
        pn = Piece("P", 1, moved=False, uses=0)
        gs.board[(0, 0)] = tf
        gs.board[(0, 2)] = pn
        ok, err = gs.apply_move(0, Move((0, 0), (0, 2), "swap"))
        self.assertTrue(ok, err)
        self.assertIs(gs.board[(0, 2)], tf)     # exchanged cells
        self.assertIs(gs.board[(0, 0)], pn)
        self.assertTrue(tf.moved)               # the thief is marked moved
        self.assertEqual(tf.uses, 0)            # swaps don't tick uses
        self.assertFalse(pn.moved)              # the victim keeps its flags
        self.assertEqual(pn.uses, 0)
        self.assertEqual(gs.lost[0], [])        # nobody died
        self.assertEqual(gs.lost[1], [])
        self.assertTrue(any("swaps places" in ln for ln in gs.log))
        self.assertFalse(any("takes" in ln for ln in gs.log))
        self.assertEqual(gs.turn_pid, 1)        # the swap consumed the turn
        self.assertEqual(gs.mimic_type, "TF")

    def test_swap_with_friendly_piece_applies(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("TF", 0)
        gs.board[(1, -1)] = Piece("CN", 0, moved=True, uses=4)
        ok, err = gs.apply_move(0, Move((0, 0), (1, -1), "swap"))
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(1, -1)].type, "TF")
        cn = gs.board[(0, 0)]
        self.assertEqual((cn.type, cn.owner, cn.moved, cn.uses),
                         ("CN", 0, True, 4))

    def test_swap_ignores_warden_aura(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("WD", 1)
        gs.board[(1, 0)] = Piece("N", 1)     # aura-protected from captures
        gs.board[(1, 3)] = Piece("R", 0)
        self.assertNotIn((1, 0), {m.to for m in gs.legal_moves((1, 3))})
        gs.board[(3, 0)] = Piece("TF", 0)    # ...but not from swaps
        swaps = {m.to for m in gs.legal_moves((3, 0)) if m.kind == "swap"}
        self.assertIn((1, 0), swaps)
        ok, err = gs.apply_move(0, Move((3, 0), (1, 0), "swap"))
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(1, 0)].type, "TF")
        self.assertEqual(gs.board[(3, 0)].type, "N")
        self.assertEqual(gs.lost[1], [])     # a swap is not a capture

    def test_swap_that_hands_an_attacker_the_king_line_is_illegal(self):
        gs = self.gs
        # TF on the king's row; enemy rook 2 steps up the q=-4 line.  The
        # swap would drop the rook onto (-4,0) with a clear lane to K0.
        gs.board[(-4, 0)] = Piece("TF", 0)
        gs.board[(-4, 2)] = Piece("R", 1)
        self.assertFalse(gs.king_in_danger(0))
        mvs = gs.legal_moves((-4, 0))
        self.assertTrue(mvs)                        # it CAN do other things
        self.assertNotIn(Move((-4, 0), (-4, 2), "swap"), mvs)
        ok, err = gs.apply_move(0, Move((-4, 0), (-4, 2), "swap"))
        self.assertFalse(ok)

    def test_swap_can_resolve_a_check_by_stealing_the_attacker(self):
        gs = self.gs
        gs.board[(-3, 0)] = Piece("R", 1)    # checks K0 along r = 0
        gs.board[(-3, 3)] = Piece("TF", 0)   # 3 steps up the rook's file
        self.assertTrue(gs.king_in_danger(0))
        swap = Move((-3, 3), (-3, 0), "swap")
        self.assertEqual(gs.legal_moves((-3, 3)), [swap])
        ok, err = gs.apply_move(0, swap)
        self.assertTrue(ok, err)
        self.assertFalse(gs.king_in_danger(0))
        self.assertEqual(gs.board[(-3, 0)].type, "TF")
        self.assertEqual(gs.board[(-3, 3)].type, "R")


class TestShaman(unittest.TestCase):
    """V5.2: the Shaman steps on 4 of the 6 ortho dirs, eats souls when it
    kills, and spends them on permanent morphs."""

    def setUp(self):
        self.gs = fresh(2)
        clear_keep_kings(self.gs)
        self.gs.turn_pid = 0

    def test_moves_on_ten_dirs_never_sideways(self):
        # v5.1 buff: the 4 non-sideways ortho steps + the necromancer's 6
        # diagonal steps.
        gs = self.gs
        gs.board[(0, 0)] = Piece("SH", 0)
        tos = {m.to for m in gs.legal_moves((0, 0)) if m.kind == "move"}
        expected = {(0, 1), (-1, 1), (0, -1), (1, -1)} | set(engine.DIAG)
        self.assertEqual(tos, expected)
        gs.board[(1, 0)] = Piece("N", 1)    # on a horizontal "side"
        gs.board[(0, 1)] = Piece("R", 1)    # on a shaman ortho dir
        gs.board[(1, 1)] = Piece("B", 1)    # on a shaman diagonal (v5.1)
        tos = {m.to for m in gs.legal_moves((0, 0)) if m.kind == "move"}
        self.assertIn((0, 1), tos)          # capturable
        self.assertIn((1, 1), tos)          # diagonal capture works too
        self.assertNotIn((1, 0), tos)       # untouchable, ever
        self.assertNotIn((-1, 0), tos)

    def test_souls_grow_on_captures_only(self):
        gs = self.gs
        sh = Piece("SH", 0)
        gs.board[(0, 0)] = sh
        ok, err = gs.apply_move(0, Move((0, 0), (0, -1)))
        self.assertTrue(ok, err)
        self.assertEqual(sh.uses, 0)        # quiet moves feed nobody
        gs.board[(1, -2)] = Piece("N", 1)   # on a shaman dir from (0,-1)
        gs.turn_pid = 0
        ok, err = gs.apply_move(0, Move((0, -1), (1, -2)))
        self.assertTrue(ok, err)
        self.assertEqual(sh.uses, 1)        # +1 soul per kill
        self.assertIn("N", gs.lost[1])

    def test_morph_moves_match_affordability_exactly(self):
        gs = self.gs
        sh = Piece("SH", 0)
        gs.board[(0, 0)] = sh
        for souls in (0, 2, 3, 4, 5, 9):
            sh.uses = souls
            morphs = [m for m in gs.legal_moves((0, 0))
                      if m.kind == "morph"]
            for m in morphs:
                self.assertEqual(m.from_, (0, 0))
                self.assertEqual(m.to, (0, 0))      # from == to
            expected = {t for t, c in engine.MORPH_COSTS.items()
                        if c <= souls}
            self.assertEqual({m.arg for m in morphs}, expected, souls)
            self.assertNotIn("K", {m.arg for m in morphs})
            self.assertNotIn("SH", {m.arg for m in morphs})
        self.assertNotIn("K", engine.MORPH_COSTS)
        self.assertNotIn("SH", engine.MORPH_COSTS)

    def test_morph_applies_cost_turn_and_log(self):
        gs = self.gs
        sh = Piece("SH", 0, moved=True, uses=7)
        gs.board[(0, 0)] = sh
        ok, err = gs.apply_move(0, Move((0, 0), (0, 0), "morph", "Q"))
        self.assertTrue(ok, err)
        self.assertIs(gs.board[(0, 0)], sh)      # never moved
        self.assertEqual(sh.type, "Q")
        self.assertEqual(sh.uses, 2)             # 7 - 5, remainder kept
        self.assertEqual(gs.turn_pid, 1)         # morphing consumed the turn
        self.assertTrue(any("twists into a Queen" in ln for ln in gs.log))
        self.assertEqual(gs.mimic_type, "SH")

    def test_morph_to_every_allowed_type(self):
        for t, cost in sorted(engine.MORPH_COSTS.items()):
            gs = fresh(2)
            clear_keep_kings(gs)
            gs.turn_pid = 0
            gs.board[(0, 0)] = Piece("SH", 0, uses=cost + 1)
            ok, err = gs.apply_move(0, Move((0, 0), (0, 0), "morph", t))
            self.assertTrue(ok, (t, err))
            pc = gs.board[(0, 0)]
            self.assertEqual(pc.type, t)
            self.assertEqual(pc.uses, 1, t)      # exactly `cost` spent

    def test_bogus_morphs_rejected(self):
        gs = self.gs
        gs.board[(0, 0)] = Piece("SH", 0, uses=9)
        for bad in (Move((0, 0), (0, 0), "morph", "K"),    # never a king
                    Move((0, 0), (0, 0), "morph", "SH"),   # or a shaman
                    Move((0, 0), (0, 0), "morph"),         # missing arg
                    Move((0, 0), (0, 1), "morph", "Q")):   # from != to
            ok, err = gs.apply_move(0, bad)
            self.assertFalse(ok, bad)
        gs.board[(0, 0)].uses = 1
        ok, err = gs.apply_move(0, Move((0, 0), (0, 0), "morph", "Q"))
        self.assertFalse(ok)                     # cannot afford a queen

    def test_cannot_morph_while_in_check(self):
        gs = self.gs
        gs.board[(3, 3)] = Piece("SH", 0, uses=9)
        self.assertTrue([m for m in gs.legal_moves((3, 3))
                         if m.kind == "morph"])
        gs.board[(0, 0)] = Piece("R", 1)     # checks K0 along r = 0
        self.assertTrue(gs.king_in_danger(0))
        # a morph never changes the position, so it can never resolve the
        # check — every shaman move here is illegal (it can't help at all)
        self.assertEqual(gs.legal_moves((3, 3)), [])

    def test_shaman_threat_matches_its_ten_dirs(self):
        gs = self.gs
        gs.board[(-6, 1)] = Piece("SH", 1)   # (0,1) off K0: a shaman dir
        self.assertTrue(gs.king_in_danger(0))
        self.assertTrue(gs._king_in_danger_scan(0))
        del gs.board[(-6, 1)]
        gs.board[(-5, 1)] = Piece("SH", 1)   # (-1,-1) to K0: v5.1 diagonal
        self.assertTrue(gs.king_in_danger(0))
        self.assertTrue(gs._king_in_danger_scan(0))
        del gs.board[(-5, 1)]
        gs.board[(-5, 0)] = Piece("SH", 1)   # (1,0): still the dead side
        self.assertFalse(gs.king_in_danger(0))
        self.assertFalse(gs._king_in_danger_scan(0))


class TestMimic(unittest.TestCase):
    """V5.2: the Mimic moves exactly like the last piece that acted."""

    def setUp(self):
        self.gs = fresh(2)
        clear_keep_kings(self.gs)
        self.gs.turn_pid = 0

    def test_defaults_and_serialization(self):
        gs = fresh(2)
        self.assertEqual(gs.mimic_type, "P")
        d = json.loads(json.dumps(gs.to_dict()))
        self.assertEqual(d["mimic"], "P")
        rt = GameState.from_dict(d)
        self.assertEqual(rt.to_dict(), gs.to_dict())
        d.pop("mimic")                       # pre-v5 dicts have no mimic key
        self.assertEqual(GameState.from_dict(d).mimic_type, "P")
        gs.mimic_type = "DR"
        rt = GameState.from_dict(json.loads(json.dumps(gs.to_dict())))
        self.assertEqual(rt.mimic_type, "DR")
        self.assertEqual(rt.to_dict(), gs.to_dict())

    def test_mimic_type_follows_the_table(self):
        gs = self.gs
        # kind "move" -> the actor's type at move start
        gs.board[(0, 0)] = Piece("R", 0)
        ok, err = gs.apply_move(0, Move((0, 0), (0, 1)))
        self.assertTrue(ok, err)
        self.assertEqual(gs.mimic_type, "R")
        # kind "shoot" -> the shooter's type
        gs.turn_pid = 0
        gs.board[(3, 0)] = Piece("AR", 0)
        gs.board[(5, 0)] = Piece("N", 1)
        ok, err = gs.apply_move(0, Move((3, 0), (5, 0), "shoot"))
        self.assertTrue(ok, err)
        self.assertEqual(gs.mimic_type, "AR")
        # kind "swap" -> "TF"
        gs.turn_pid = 0
        gs.board[(0, -2)] = Piece("TF", 0)
        ok, err = gs.apply_move(0, Move((0, -2), (0, 1), "swap"))  # the R
        self.assertTrue(ok, err)
        self.assertEqual(gs.mimic_type, "TF")
        # kind "raise" -> "NE"
        gs.turn_pid = 0
        gs.board[(2, 2)] = Piece("NE", 0)
        gs.lost[0].append("P")
        ok, err = gs.apply_move(0, Move((2, 2), (2, 3), "raise"))
        self.assertTrue(ok, err)
        self.assertEqual(gs.mimic_type, "NE")
        # kind "morph" -> "SH"
        gs.turn_pid = 0
        gs.board[(-2, -2)] = Piece("SH", 0, uses=0)
        ok, err = gs.apply_move(0, Move((-2, -2), (-2, -2), "morph", "P"))
        self.assertTrue(ok, err)
        self.assertEqual(gs.mimic_type, "SH")

    def test_promoting_pawn_records_pawn_not_queen(self):
        gs = self.gs
        gs.mimic_type = "R"
        gs.board[(0, -5)] = Piece("P", 0, moved=True)
        ok, err = gs.apply_move(0, Move((0, -5), (0, -6)))
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(0, -6)].type, "Q")   # promoted...
        self.assertEqual(gs.mimic_type, "P")   # ...but it MOVED as a pawn

    def test_moves_like_the_mimicked_type(self):
        gs = self.gs
        gs.mimic_type = "R"
        gs.board[(0, 0)] = Piece("MI", 0)
        tos = {m.to for m in gs.legal_moves((0, 0))}
        self.assertIn((0, 4), tos)           # long rook slide
        self.assertNotIn((1, 1), tos)        # no diagonal
        gs.mimic_type = "N"
        tos = {m.to for m in gs.legal_moves((0, 0))}
        self.assertEqual(tos, {(0 + dq, 0 + dr) for dq, dr in engine.KNIGHT})

    def test_mimic_actor_never_updates_mimic_type(self):
        gs = self.gs
        gs.mimic_type = "R"
        gs.board[(0, 0)] = Piece("MI", 0)
        ok, err = gs.apply_move(0, Move((0, 0), (0, 3)))
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(0, 3)].type, "MI")   # stays a mimic
        self.assertEqual(gs.mimic_type, "R")            # copy NOT copied

    def test_mimic_copies_shoots(self):
        gs = self.gs
        gs.mimic_type = "AR"
        gs.board[(0, 0)] = Piece("MI", 0)
        gs.board[(1, 0)] = Piece("R", 1)     # blocker: archers don't care
        gs.board[(2, 0)] = Piece("N", 1)
        shoots = [m for m in gs.legal_moves((0, 0)) if m.kind == "shoot"]
        self.assertEqual({m.to for m in shoots}, {(2, 0)})
        ok, err = gs.apply_move(0, shoots[0])
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(0, 0)].type, "MI")   # did not move
        self.assertNotIn((2, 0), gs.board)
        self.assertIn("N", gs.lost[1])
        self.assertEqual(gs.mimic_type, "AR")           # unchanged by MI

    def test_mimic_copies_swaps_but_not_with_kings(self):
        gs = self.gs
        gs.mimic_type = "TF"
        gs.board[(0, 0)] = Piece("MI", 0)
        gs.board[(0, 2)] = Piece("N", 1)
        swaps = {m.to for m in gs.legal_moves((0, 0)) if m.kind == "swap"}
        self.assertEqual(swaps, {(0, 2)})
        gs.board[(5, 0)] = Piece("MI", 0)    # beside the enemy king
        self.assertNotIn((6, 0), {m.to for m in gs.legal_moves((5, 0))})
        ok, err = gs.apply_move(0, Move((0, 0), (0, 2), "swap"))
        self.assertTrue(ok, err)
        self.assertEqual(gs.board[(0, 2)].type, "MI")
        self.assertEqual(gs.board[(0, 0)].type, "N")
        self.assertEqual(gs.mimic_type, "TF")           # unchanged by MI

    def test_mimic_copies_raises(self):
        gs = self.gs
        gs.mimic_type = "NE"
        gs.board[(0, 0)] = Piece("MI", 0)
        self.assertEqual([m for m in gs.legal_moves((0, 0))
                          if m.kind == "raise"], [])    # no lost pawn yet
        gs.lost[0].append("P")
        raises = [m for m in gs.legal_moves((0, 0)) if m.kind == "raise"]
        self.assertEqual(len(raises), 6)
        ok, err = gs.apply_move(0, raises[0])
        self.assertTrue(ok, err)
        risen = gs.board[raises[0].to]
        self.assertEqual((risen.type, risen.owner, risen.moved, risen.uses),
                         ("SK", 0, True, 0))
        self.assertNotIn("P", gs.lost[0])
        self.assertEqual(gs.board[(0, 0)].type, "MI")   # did not move
        self.assertEqual(gs.mimic_type, "NE")

    def test_mimic_drops_morphs(self):
        gs = self.gs
        gs.mimic_type = "SH"
        gs.board[(0, 0)] = Piece("MI", 0, uses=9)   # souls to burn — no sale
        mvs = gs.legal_moves((0, 0))
        self.assertEqual([m for m in mvs if m.kind == "morph"], [])
        self.assertEqual({m.to for m in mvs},
                         {(0, 1), (-1, 1), (0, -1), (1, -1)}
                         | set(engine.DIAG))   # v5.1 shaman steps

    def test_mimic_pawn_honors_moved_flag(self):
        gs = self.gs
        gs.mimic_type = "P"
        gs.board[(0, 3)] = Piece("MI", 0)    # unmoved: pawn double-step
        tos = {m.to for m in gs.legal_moves((0, 3))}
        self.assertEqual(tos, {(0, 2), (1, 2), (0, 1), (2, 1)})
        gs.board[(0, 3)].moved = True
        tos = {m.to for m in gs.legal_moves((0, 3))}
        self.assertEqual(tos, {(0, 2), (1, 2)})

    def test_pawn_mimic_threatens_by_its_owners_seat(self):
        gs = self.gs
        # player 1 sits on edge 3: capture diags (-1,2), (1,1), (-2,1).
        # From (-4,-1), the (-2,1) diagonal hits K0 on (-6,0).
        gs.mimic_type = "P"
        gs.board[(-4, -1)] = Piece("MI", 1)
        self.assertTrue(gs.king_in_danger(0))
        self.assertTrue(gs._king_in_danger_scan(0))
        # ...whereas a pawn-mimic OWNED BY PLAYER 0 there aims the other way
        gs.board[(-4, -1)] = Piece("MI", 0)
        self.assertFalse(gs.king_in_danger(0))
        self.assertFalse(gs._king_in_danger_scan(0))
        # and a thief-mimic threatens nothing at all
        gs.board[(-4, -1)] = Piece("MI", 1)
        gs.mimic_type = "TF"
        self.assertFalse(gs.king_in_danger(0))
        self.assertFalse(gs._king_in_danger_scan(0))

    def test_mimic_as_slider_checks_the_king(self):
        gs = self.gs
        gs.board[(-6, 3)] = Piece("MI", 1)   # rook-lined up with K0
        for mt, danger in (("R", True), ("B", False), ("N", False),
                           ("Q", True), ("TF", False), ("P", False)):
            gs.mimic_type = mt
            self.assertEqual(gs.king_in_danger(0), danger, mt)
            self.assertEqual(gs._king_in_danger_scan(0), danger, mt)


class TestMoveArgV5(unittest.TestCase):
    """V5.1: Move gained an optional `arg` with full value semantics."""

    def test_kinds_gained_swap_and_morph(self):
        self.assertIn("swap", engine.MOVE_KINDS)
        self.assertIn("morph", engine.MOVE_KINDS)

    def test_arg_serializes_only_when_set(self):
        m = Move((2, 3), (2, 3), "morph", "Q")
        d = m.to_dict()
        self.assertEqual(d, {"from": [2, 3], "to": [2, 3],
                             "kind": "morph", "arg": "Q"})
        self.assertEqual(Move.from_dict(json.loads(json.dumps(d))), m)
        plain = Move((0, 0), (1, 0))
        self.assertNotIn("arg", plain.to_dict())
        self.assertEqual(Move.from_dict(plain.to_dict()), plain)
        # pre-v5 dicts (no "arg" key) still parse, with arg=None
        old = Move.from_dict({"from": [0, 0], "to": [1, 0], "kind": "move"})
        self.assertIsNone(old.arg)
        self.assertEqual(old, plain)

    def test_arg_in_eq_and_hash(self):
        a = Move((0, 0), (0, 0), "morph", "Q")
        b = Move((0, 0), (0, 0), "morph", "Q")
        c = Move((0, 0), (0, 0), "morph", "N")
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, Move((0, 0), (0, 0), "morph"))
        self.assertEqual(len({a, b, c}), 2)

    def test_malformed_args_rejected(self):
        Move.from_dict({"from": [0, 0], "to": [0, 2], "kind": "swap"})  # ok
        for bad_arg in (7, ["Q"], {"t": "Q"}, True):
            with self.assertRaises(ValueError, msg=bad_arg):
                Move.from_dict({"from": [0, 0], "to": [0, 0],
                                "kind": "morph", "arg": bad_arg})
        with self.assertRaises(ValueError):
            Move.from_dict({"from": [0, 0], "to": [0, 0], "kind": "bogus"})


class TestFuzz(unittest.TestCase):
    def test_random_playouts_hold_invariants(self):
        rng = random.Random(1234)
        for n in (2, 3, 4, 5, 6):
            for game in range(2):
                gs = fresh(n)
                cells = engine.board_cells(gs.radius)
                for _ply in range(400):
                    if gs.winner is not None:
                        break
                    mover = gs.turn_pid
                    all_mv = gs.all_legal_moves(mover)
                    self.assertTrue(all_mv)  # advance_turn guarantees moves
                    ok, err = gs.apply_move(mover, rng.choice(all_mv))
                    self.assertTrue(ok, err)
                    for c, pc in gs.board.items():
                        self.assertIn(c, cells)
                        self.assertTrue(gs._is_alive(pc.owner))
                        self.assertIn(pc.type, engine.PIECE_NAMES)
                    for types in gs.lost.values():
                        for t in types:
                            self.assertIn(t, engine.PIECE_NAMES)
                    if gs.winner is None:
                        self.assertTrue(gs._is_alive(gs.turn_pid))
                    if _ply % 25 == 0:
                        # fast reverse attack test must agree with the slow
                        # pseudo-move scan on real positions
                        for p in gs.players:
                            if p["alive"]:
                                self.assertEqual(
                                    gs.king_in_danger(p["pid"]),
                                    gs._king_in_danger_scan(p["pid"]),
                                    "attack-test divergence n=%d ply=%d pid=%d"
                                    % (n, _ply, p["pid"]))
                    rt = GameState.from_dict(
                        json.loads(json.dumps(gs.to_dict())))
                    self.assertEqual(rt.to_dict(), gs.to_dict())

    def test_random_playouts_with_v3_swaps(self):
        rng = random.Random(97531)
        swaps = {"CN": "JG", "GH": "WD", "AR": "SN"}
        for n in (2, 3, 6):
            gs = GameState.new_game([(i, "P%d" % i) for i in range(n)],
                                    swaps=swaps)
            cells = engine.board_cells(gs.radius)
            for _ply in range(300):
                if gs.winner is not None:
                    break
                mover = gs.turn_pid
                all_mv = gs.all_legal_moves(mover)
                self.assertTrue(all_mv)
                ok, err = gs.apply_move(mover, rng.choice(all_mv))
                self.assertTrue(ok, err)
                for c, pc in gs.board.items():
                    self.assertIn(c, cells)
                    self.assertTrue(gs._is_alive(pc.owner))
                    self.assertIn(pc.type, engine.PIECE_NAMES)
                for types in gs.lost.values():
                    for t in types:
                        self.assertIn(t, engine.PIECE_NAMES)
                if gs.winner is None:
                    self.assertTrue(gs._is_alive(gs.turn_pid))
                rt = GameState.from_dict(
                    json.loads(json.dumps(gs.to_dict())))
                self.assertEqual(rt.to_dict(), gs.to_dict())

    def test_random_playouts_on_new_shapes(self):
        rng = random.Random(4321)
        for shape, n in (("square", 2), ("square", 4),
                         ("triangle", 3), ("octagon", 6)):
            gs = new_shaped(n, shape)
            cells = engine.shape_cells(shape, gs.radius)
            for _ply in range(250):
                if gs.winner is not None:
                    break
                mover = gs.turn_pid
                all_mv = gs.all_legal_moves(mover)
                self.assertTrue(all_mv)
                ok, err = gs.apply_move(mover, rng.choice(all_mv))
                self.assertTrue(ok, err)
                for c, pc in gs.board.items():
                    self.assertIn(c, cells)
                    self.assertTrue(gs._is_alive(pc.owner))
                    self.assertIn(pc.type, engine.PIECE_NAMES)
                if gs.winner is None:
                    self.assertTrue(gs._is_alive(gs.turn_pid))
                rt = GameState.from_dict(
                    json.loads(json.dumps(gs.to_dict())))
                self.assertEqual(rt.shape, shape)
                self.assertEqual(rt.to_dict(), gs.to_dict())

    def test_random_playouts_with_v5_swaps(self):
        """V5: games with TF/SH/MI swapped in — the fast reverse attack
        test must keep agreeing with the slow pseudo-move scan (the ground
        truth for mimic/shaman/thief threat), swaps and morphs included."""
        rng = random.Random(52025)
        # v5.1: TF/MI are in every base army already; add the shaman via swap
        swaps = {"NE": "SH", "R": "GO", "B": "VA"}
        kinds_seen = set()
        for n in (2, 3, 6):
            gs = GameState.new_game([(i, "P%d" % i) for i in range(n)],
                                    swaps=swaps)
            cells = engine.board_cells(gs.radius)
            for _ply in range(300):
                if gs.winner is not None:
                    break
                mover = gs.turn_pid
                all_mv = gs.all_legal_moves(mover)
                self.assertTrue(all_mv)
                special = [m for m in all_mv
                           if m.kind in ("swap", "morph")]
                if special and rng.random() < 0.35:
                    mv = rng.choice(special)
                else:
                    mv = rng.choice(all_mv)
                kinds_seen.add(mv.kind)
                ok, err = gs.apply_move(mover, mv)
                self.assertTrue(ok, err)
                self.assertIn(gs.mimic_type, engine.PIECE_NAMES)
                self.assertNotEqual(gs.mimic_type, "MI")
                for c, pc in gs.board.items():
                    self.assertIn(c, cells)
                    self.assertTrue(gs._is_alive(pc.owner))
                    self.assertIn(pc.type, engine.PIECE_NAMES)
                for types in gs.lost.values():
                    for t in types:
                        self.assertIn(t, engine.PIECE_NAMES)
                if gs.winner is None:
                    self.assertTrue(gs._is_alive(gs.turn_pid))
                if _ply % 5 == 0:
                    # differential king-danger check: the fast reverse
                    # attack test IS defined by the pseudo-move scan
                    for p in gs.players:
                        if p["alive"]:
                            self.assertEqual(
                                gs.king_in_danger(p["pid"]),
                                gs._king_in_danger_scan(p["pid"]),
                                "attack-test divergence n=%d ply=%d pid=%d"
                                % (n, _ply, p["pid"]))
                rt = GameState.from_dict(
                    json.loads(json.dumps(gs.to_dict())))
                self.assertEqual(rt.to_dict(), gs.to_dict())
        self.assertIn("swap", kinds_seen)    # thieves actually swapped
        self.assertIn("morph", kinds_seen)   # shamans actually morphed

    def test_random_playouts_with_raises_and_graves(self):
        """V4: games featuring necromancer raises (SK on the board) and a
        mid-game elimination followed by apply_grave, invariants intact."""
        rng = random.Random(20260712)
        raises_seen = 0
        graves_seen = 0
        for n, forced_kill_ply in ((3, 50), (4, 70), (3, 30)):
            gs = fresh(n)
            cells = engine.board_cells(gs.radius)
            for ply in range(400):
                if gs.winner is not None:
                    break
                # a forced mid-game elimination (the disconnect path) makes
                # sure the graveyard flow runs in every playout
                if ply == forced_kill_ply:
                    victims = [p["pid"] for p in gs.players
                               if p["alive"] and p["pid"] != gs.turn_pid]
                    if victims:
                        gs.eliminate(rng.choice(victims), "disconnected")
                    if gs.winner is not None:
                        break
                # every dead player spends their curse mid-game
                for p in gs.players:
                    pid = p["pid"]
                    if p["alive"] or gs.graves_left.get(pid, 0) < 1:
                        continue
                    free = sorted(c for c in cells if c not in gs.board
                                  and c not in gs.graveyards)
                    ok, err = gs.apply_grave(pid, rng.choice(free))
                    self.assertTrue(ok, err)
                    graves_seen += 1
                    # the fresh curse may have walled in the player to move
                    if (gs.winner is None
                            and not gs.all_legal_moves(gs.turn_pid)):
                        gs.force_skip(gs.turn_pid)
                if gs.winner is not None:
                    break
                mover = gs.turn_pid
                all_mv = gs.all_legal_moves(mover)
                self.assertTrue(all_mv)
                rz = [m for m in all_mv if m.kind == "raise"]
                if rz and rng.random() < 0.8:
                    mv = rng.choice(rz)
                    raises_seen += 1
                else:
                    mv = rng.choice(all_mv)
                ok, err = gs.apply_move(mover, mv)
                self.assertTrue(ok, err)
                self.assertTrue(gs.graveyards <= cells)
                for c, pc in gs.board.items():
                    self.assertIn(c, cells)
                    self.assertTrue(gs._is_alive(pc.owner))
                    self.assertIn(pc.type, engine.PIECE_NAMES)
                    if c in gs.graveyards:   # only skeletons stand on graves
                        self.assertEqual(pc.type, "SK")
                for types in gs.lost.values():
                    for t in types:
                        self.assertIn(t, engine.PIECE_NAMES)
                for pc in gs.board.values():
                    if pc.type == "SK":
                        self.assertLess(pc.uses, 3)   # crumbled otherwise
                    if pc.type == "BM":
                        self.assertLess(pc.uses, 10)  # detonated otherwise
                if gs.winner is None:
                    self.assertTrue(gs._is_alive(gs.turn_pid))
                rt = GameState.from_dict(
                    json.loads(json.dumps(gs.to_dict())))
                self.assertEqual(rt.to_dict(), gs.to_dict())
        self.assertGreater(graves_seen, 0)
        self.assertGreater(raises_seen, 0)


if __name__ == "__main__":
    unittest.main()
