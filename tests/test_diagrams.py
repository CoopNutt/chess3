"""Tests for diagrams.py — headless movement-diagram rendering.

SDL_VIDEODRIVER must be set to "dummy" BEFORE pygame is imported so the
suite runs without any display.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

import pygame

import diagrams
import engine
import icons


def _reset_style():
    icons.set_style(rim=None, glow=None, ink=None, glyph=None)


class TestDiagrams(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        _reset_style()

    def tearDown(self):
        _reset_style()

    def test_all_24_types_render_non_blank(self):
        """Every type in TYPE_ORDER renders at widths 180 and 240."""
        self.assertEqual(len(icons.TYPE_ORDER), 24)
        for ptype in icons.TYPE_ORDER:
            self.assertIn(ptype, engine.PIECE_NAMES,
                          "engine lacks type %s" % ptype)
            for width in (180, 240):
                surf = diagrams.movement_diagram(ptype, width)
                self.assertEqual(surf.get_width(), width)
                self.assertGreater(surf.get_height(), 0)
                buf = pygame.image.tobytes(surf, "RGBA")
                self.assertTrue(any(b != 0 for b in buf),
                                "%s at width %d rendered blank"
                                % (ptype, width))

    def test_cached_per_type_and_width(self):
        """The same (ptype, width) returns the identical cached surface."""
        a = diagrams.movement_diagram("Q", 240)
        b = diagrams.movement_diagram("Q", 240)
        self.assertIs(a, b)
        c = diagrams.movement_diagram("Q", 180)
        self.assertIsNot(a, c)

    def test_cache_is_style_aware(self):
        """A style change misses the old cache entry (V3.3 fingerprint)."""
        a = diagrams.movement_diagram("Q", 240)
        icons.set_style(glow=(255, 200, 80))
        try:
            b = diagrams.movement_diagram("Q", 240)
            self.assertIsNot(a, b)
            # same style again -> cached surface comes back
            self.assertIs(diagrams.movement_diagram("Q", 240), b)
        finally:
            _reset_style()
        # back at the default style, the original entry is still valid
        self.assertIs(diagrams.movement_diagram("Q", 240), a)

    def test_clear_cache(self):
        """clear_cache() drops cached surfaces (main.set_theme hook)."""
        a = diagrams.movement_diagram("R", 240)
        self.assertIs(diagrams.movement_diagram("R", 240), a)
        diagrams.clear_cache()
        b = diagrams.movement_diagram("R", 240)
        self.assertIsNot(a, b)

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            diagrams.movement_diagram("XX", 240)

    def test_archer_demo_produces_shoot_markers(self):
        """The AR diagram contains >= 1 shoot marker (movegen, not pixels)."""
        window = engine.board_cells(diagrams.window_radius("AR"))
        moves = diagrams.demo_moves("AR")
        shoots = [m for m in moves if m.kind == "shoot" and m.to in window]
        self.assertGreaterEqual(len(shoots), 1)
        # and the surface renders without error
        diagrams.movement_diagram("AR", 240)

    def test_catapult_demo_produces_range3_shoot(self):
        """The CT demo yields a shoot at exactly 3 cells, inside the window."""
        window = engine.board_cells(diagrams.window_radius("CT"))
        moves = diagrams.demo_moves("CT")
        shoots = [m for m in moves if m.kind == "shoot" and m.to in window]
        self.assertGreaterEqual(len(shoots), 1)
        for m in shoots:
            self.assertEqual(engine.hex_dist(m.from_, m.to), 3)

    def test_necromancer_demo_produces_raise_markers(self):
        """The NE demo (one lost pawn) yields raise moves in the window."""
        window = engine.board_cells(diagrams.window_radius("NE"))
        moves = diagrams.demo_moves("NE")
        raises_ = [m for m in moves if m.kind == "raise" and m.to in window]
        self.assertGreaterEqual(len(raises_), 1)

    def test_juggernaut_demo_capture_and_quiet_endpoint(self):
        """The JG demo shows >= 1 capture AND >= 1 quiet charge endpoint
        (the charge stopping short of a friendly blocker), all in-window."""
        gs = diagrams.demo_state("JG")
        window = engine.board_cells(diagrams.window_radius("JG"))
        moves = [m for m in diagrams.demo_moves("JG") if m.to in window]
        captures = [m for m in moves if m.kind == "move" and m.to in gs.board]
        quiets = [m for m in moves if m.kind == "move"
                  and m.to not in gs.board]
        self.assertGreaterEqual(len(captures), 1)
        self.assertGreaterEqual(len(quiets), 1)
        for m in captures:
            self.assertNotEqual(gs.board[m.to].owner, 0)
        # the friendly blocker at (0, 3) stops the charge on (0, 2)
        self.assertIn((0, 2), [m.to for m in quiets])
        diagrams.movement_diagram("JG", 240)

    def test_sniper_demo_produces_diag_shoot_markers(self):
        """The SN demo yields >= 1 in-window shoot at exactly 2 diag steps
        (hex distance 4), shooting straight over a blocker."""
        window = engine.board_cells(diagrams.window_radius("SN"))
        moves = diagrams.demo_moves("SN")
        shoots = [m for m in moves if m.kind == "shoot" and m.to in window]
        self.assertGreaterEqual(len(shoots), 1)
        for m in shoots:
            self.assertEqual(engine.hex_dist(m.from_, m.to), 4)
        # (2, 2) sits behind the blocker on (1, 1) — shot over it
        self.assertIn((2, 2), [m.to for m in shoots])
        diagrams.movement_diagram("SN", 240)

    def test_warden_demo_is_bare_king_steps(self):
        """The WD demo (no extra pieces) is exactly the 12 quiet king-steps."""
        gs = diagrams.demo_state("WD")
        self.assertEqual([c for c in gs.board if c != (0, 0)], [])
        moves = diagrams.demo_moves("WD")
        self.assertEqual(len(moves), 12)
        expected = {d for d in engine.ORTHO} | {d for d in engine.DIAG}
        self.assertEqual({m.to for m in moves}, expected)
        for m in moves:
            self.assertEqual(m.kind, "move")
        window = engine.board_cells(diagrams.window_radius("WD"))
        self.assertTrue(all(m.to in window for m in moves))
        diagrams.movement_diagram("WD", 240)

    def test_skeleton_demo_forward_and_captures(self):
        """The SK demo (v4) shows the two quiet forward steps AND all 3
        forward-diagonal captures (>= 1 capture marker), with no
        double-step — everything inside the window."""
        gs = diagrams.demo_state("SK")
        window = engine.board_cells(diagrams.window_radius("SK"))
        moves = diagrams.demo_moves("SK")
        self.assertTrue(all(m.to in window for m in moves))
        self.assertTrue(all(m.kind == "move" for m in moves))
        quiets = {m.to for m in moves if m.to not in gs.board}
        captures = {m.to for m in moves if m.to in gs.board}
        # seat edge 0: forward steps F1=(0,-1), F2=(1,-1)
        self.assertEqual(quiets, {(0, -1), (1, -1)})
        # the 3 capture diagonals, each holding a demo enemy
        self.assertGreaterEqual(len(captures), 1)
        self.assertEqual(captures, {(1, -2), (-1, -1), (2, -1)})
        for c in captures:
            self.assertNotEqual(gs.board[c].owner, 0)
        # no pawn-style double-step for skeletons
        self.assertNotIn((0, -2), {m.to for m in moves})
        self.assertNotIn((2, -2), {m.to for m in moves})
        diagrams.movement_diagram("SK", 240)

    def test_thief_demo_produces_swap_targets(self):
        """The TF demo (v5) yields swap moves on BOTH the gray enemy pawn
        and the blue friendly pawn — never a capture — all in-window."""
        gs = diagrams.demo_state("TF")
        window = engine.board_cells(diagrams.window_radius("TF"))
        moves = diagrams.demo_moves("TF")
        swaps = [m for m in moves if m.kind == "swap"]
        self.assertGreaterEqual(len(swaps), 2)
        self.assertTrue(all(m.to in window for m in swaps))
        targets = {m.to for m in swaps}
        self.assertIn((2, 0), targets)     # gray enemy pawn
        self.assertIn((-1, 1), targets)    # blue FRIENDLY pawn
        for m in swaps:
            self.assertIn(m.to, gs.board)  # a swap partner always exists
            self.assertNotEqual(gs.board[m.to].type, "K")
        # a thief NEVER captures: its plain moves all end on empty cells
        for m in moves:
            if m.kind == "move":
                self.assertNotIn(m.to, gs.board)
        diagrams.movement_diagram("TF", 240)

    def test_swap_marker_color_exposed_and_painted(self):
        """SWAP_COLOR is exported, distinct from every other marker color,
        and actually painted on the TF diagram (the teal double ring)."""
        self.assertEqual(len(diagrams.SWAP_COLOR), 3)
        for other in (diagrams.QUIET_COLOR, diagrams.CAPTURE_COLOR,
                      diagrams.SHOOT_COLOR, diagrams.RAISE_COLOR,
                      diagrams.HATCH_COLOR):
            self.assertNotEqual(diagrams.SWAP_COLOR, other)
        surf = diagrams.movement_diagram("TF", 240)
        buf = pygame.image.tobytes(surf, "RGB")
        swap = bytes(diagrams.SWAP_COLOR)
        idx = buf.find(swap)
        while idx != -1 and idx % 3 != 0:      # must be pixel-aligned
            idx = buf.find(swap, idx + 1)
        self.assertNotEqual(idx, -1,
                            "no SWAP_COLOR pixel on the TF diagram")

    def test_shaman_demo_ten_dirs_no_sideways(self):
        """The SH demo (v5.1) shows exactly 10 quiet step dots — the 4
        non-sideways ortho steps plus the 6 diagonals — and the two
        horizontal side dirs (1,0)/(-1,0) are NOT among them. Its free
        morph moves exist in movegen but are never painted as markers."""
        gs = diagrams.demo_state("SH")
        window = engine.board_cells(diagrams.window_radius("SH"))
        moves = diagrams.demo_moves("SH")
        steps = [m for m in moves if m.kind == "move"]
        self.assertEqual(len(steps), 10)
        offs = {m.to for m in steps}
        self.assertEqual(offs, {(0, 1), (-1, 1), (0, -1), (1, -1)}
                         | set(engine.DIAG))
        self.assertNotIn((1, 0), offs)
        self.assertNotIn((-1, 0), offs)
        for m in steps:
            self.assertNotIn(m.to, gs.board)   # quiet dots, not captures
            self.assertIn(m.to, window)
        # the 0-soul morphs (P and SK cost 0) are in the movegen...
        morphs = [m for m in moves if m.kind == "morph"]
        self.assertEqual({m.arg for m in morphs}, {"P", "SK"})
        for m in morphs:
            self.assertEqual(m.from_, (0, 0))
            self.assertEqual(m.to, (0, 0))
        # ...but the rendered diagram paints no capture ring anywhere (an
        # unfiltered morph would drop one on the shaman's own cell)
        surf = diagrams.movement_diagram("SH", 240)
        buf = pygame.image.tobytes(surf, "RGB")
        cap = bytes(diagrams.CAPTURE_COLOR)
        idx = buf.find(cap)
        while idx != -1 and idx % 3 != 0:      # must be pixel-aligned
            idx = buf.find(cap, idx + 1)
        self.assertEqual(idx, -1,
                         "capture ring painted on the SH diagram")

    def test_mimic_demo_knight_pattern(self):
        """The MI demo (v5) pins mimic_type to "N": the diagram is exactly
        the 12 quiet knight jumps, all inside the window."""
        gs = diagrams.demo_state("MI")
        self.assertEqual(gs.mimic_type, "N")
        window = engine.board_cells(diagrams.window_radius("MI"))
        moves = diagrams.demo_moves("MI")
        self.assertEqual(len(moves), 12)
        self.assertEqual({m.kind for m in moves}, {"move"})
        self.assertEqual({m.to for m in moves},
                         {(dq, dr) for dq, dr in engine.KNIGHT})
        self.assertTrue(all(m.to in window for m in moves))
        self.assertTrue(all(m.to not in gs.board for m in moves))
        diagrams.movement_diagram("MI", 240)

    def test_markers_match_engine_movegen(self):
        """demo_moves is exactly the engine movegen for the demo state."""
        for ptype in ("CN", "BM", "GH", "P", "JG", "SN", "WD", "SK",
                      "TF", "SH", "MI"):
            gs = diagrams.demo_state(ptype)
            expected = gs.legal_moves((0, 0))
            got = diagrams.demo_moves(ptype)
            self.assertEqual(sorted((m.from_, m.to, m.kind) for m in got),
                             sorted((m.from_, m.to, m.kind)
                                    for m in expected))


if __name__ == "__main__":
    unittest.main()
