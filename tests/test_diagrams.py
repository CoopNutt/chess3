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

    def test_all_20_types_render_non_blank(self):
        """Every type in TYPE_ORDER renders at widths 180 and 240."""
        self.assertEqual(len(icons.TYPE_ORDER), 20)
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

    def test_markers_match_engine_movegen(self):
        """demo_moves is exactly the engine movegen for the demo state."""
        for ptype in ("CN", "BM", "GH", "P", "JG", "SN", "WD"):
            gs = diagrams.demo_state(ptype)
            expected = gs.legal_moves((0, 0))
            got = diagrams.demo_moves(ptype)
            self.assertEqual(sorted((m.from_, m.to, m.kind) for m in got),
                             sorted((m.from_, m.to, m.kind)
                                    for m in expected))


if __name__ == "__main__":
    unittest.main()
