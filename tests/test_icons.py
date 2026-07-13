"""Tests for icons.py — headless rendering of all piece glyphs + V3.3 style.

SDL_VIDEODRIVER must be set to "dummy" BEFORE pygame is imported so the
suite runs without any display.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest

import pygame

import icons


def _reset_style():
    """Restore the classic default STYLE."""
    icons.set_style(rim=None, glow=None, ink=None, glyph=None)


def _render_bytes(ptype="K", color=None, size=48):
    """Render one piece on a fixed background and return the RGB bytes."""
    if color is None:
        color = icons.PLAYER_COLORS[3]
    surf = pygame.Surface((size + 20, size + 20))
    surf.fill((90, 90, 96))
    icons.draw_piece(surf, ptype, color, size,
                     (surf.get_width() // 2, surf.get_height() // 2))
    return pygame.image.tobytes(surf, "RGB")


class TestIcons(unittest.TestCase):
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

    def test_constants(self):
        """21 types, 6 player colors of valid (r, g, b) tuples."""
        self.assertEqual(len(icons.TYPE_ORDER), 21)
        self.assertEqual(len(set(icons.TYPE_ORDER)), 21)
        for new_type in ("CT", "VA", "GO", "JG", "SN", "WD", "SK"):
            self.assertIn(new_type, icons.TYPE_ORDER)
        self.assertEqual(len(icons.PLAYER_COLORS), 6)
        for color in icons.PLAYER_COLORS:
            self.assertEqual(len(color), 3)
            for c in color:
                self.assertIsInstance(c, int)
                self.assertTrue(0 <= c <= 255)

    def test_draw_all_types_colors_sizes(self):
        """draw_piece renders every type x 3 colors x sizes 24/36/64."""
        colors = (icons.PLAYER_COLORS[0],   # white (light body)
                  icons.PLAYER_COLORS[1],   # black (dark body)
                  icons.PLAYER_COLORS[2])   # red
        for ptype in icons.TYPE_ORDER:
            for color in colors:
                for size in (24, 36, 64):
                    surf = pygame.Surface((size + 16, size + 16))
                    surf.fill((90, 90, 96))
                    before = pygame.image.tobytes(surf, "RGB")
                    icons.draw_piece(surf, ptype, color, size,
                                     (surf.get_width() // 2,
                                      surf.get_height() // 2))
                    after = pygame.image.tobytes(surf, "RGB")
                    self.assertNotEqual(before, after,
                                        "%s at size %d drew nothing"
                                        % (ptype, size))

    def test_unknown_type_raises(self):
        surf = pygame.Surface((64, 64))
        with self.assertRaises(ValueError):
            icons.draw_piece(surf, "XX", (200, 0, 0), 36, (32, 32))

    def test_preview_size_sane(self):
        """render_all_preview returns a 21-col x 6-row grid of `cell` px."""
        for cell in (48, 64):
            surf = icons.render_all_preview(cell)
            self.assertEqual(surf.get_width(), 21 * cell)
            self.assertEqual(surf.get_height(),
                             len(icons.PLAYER_COLORS) * cell)

    def test_glyphs_pairwise_distinct(self):
        """Same-color renders of all 21 types differ pixel-for-pixel."""
        color = icons.PLAYER_COLORS[3]  # blue
        bufs = {}
        for ptype in icons.TYPE_ORDER:
            surf = pygame.Surface((80, 80))
            surf.fill((10, 10, 12))
            icons.draw_piece(surf, ptype, color, 64, (40, 40))
            bufs[ptype] = pygame.image.tobytes(surf, "RGB")
        types = list(bufs)
        for i in range(len(types)):
            for j in range(i + 1, len(types)):
                self.assertNotEqual(
                    bufs[types[i]], bufs[types[j]],
                    "glyphs %s and %s render identically"
                    % (types[i], types[j]))

    def test_glyphs_pairwise_distinct_at_36(self):
        """The pairwise-distinct guarantee also holds at size 36."""
        color = icons.PLAYER_COLORS[3]
        bufs = {}
        for ptype in icons.TYPE_ORDER:
            surf = pygame.Surface((52, 52))
            surf.fill((10, 10, 12))
            icons.draw_piece(surf, ptype, color, 36, (26, 26))
            bufs[ptype] = pygame.image.tobytes(surf, "RGB")
        types = list(bufs)
        for i in range(len(types)):
            for j in range(i + 1, len(types)):
                self.assertNotEqual(
                    bufs[types[i]], bufs[types[j]],
                    "glyphs %s and %s render identically at size 36"
                    % (types[i], types[j]))


class TestStyle(unittest.TestCase):
    """SPEC V3.3: STYLE dict + set_style partial updates + draw effects."""

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

    def test_defaults(self):
        """Default STYLE is the classic look (rim/glow off)."""
        self.assertEqual(icons.STYLE,
                         {"rim": None, "glow": None,
                          "ink": (25, 25, 30), "glyph": (245, 245, 245)})

    def test_partial_update(self):
        """set_style only touches the fields it is passed."""
        icons.set_style(glow=(120, 200, 255))
        self.assertEqual(icons.STYLE["glow"], (120, 200, 255))
        self.assertIsNone(icons.STYLE["rim"])
        self.assertEqual(icons.STYLE["ink"], (25, 25, 30))
        self.assertEqual(icons.STYLE["glyph"], (245, 245, 245))
        icons.set_style(rim=(200, 180, 90))
        self.assertEqual(icons.STYLE["rim"], (200, 180, 90))
        self.assertEqual(icons.STYLE["glow"], (120, 200, 255))
        icons.set_style()      # no-op
        self.assertEqual(icons.STYLE["rim"], (200, 180, 90))
        self.assertEqual(icons.STYLE["glow"], (120, 200, 255))
        # explicit None resets a field to its classic default
        icons.set_style(glow=None, ink=None)
        self.assertIsNone(icons.STYLE["glow"])
        self.assertEqual(icons.STYLE["ink"], (25, 25, 30))
        self.assertEqual(icons.STYLE["rim"], (200, 180, 90))

    def test_fingerprint_tracks_style(self):
        fp0 = icons.style_fingerprint()
        icons.set_style(glow=(255, 120, 40))
        fp1 = icons.style_fingerprint()
        self.assertNotEqual(fp0, fp1)
        icons.set_style(glow=None)
        self.assertEqual(icons.style_fingerprint(), fp0)

    def test_draw_consults_style_every_call(self):
        """glow/rim/ink/glyph each change the render; reset restores it."""
        base = _render_bytes("K")
        # deterministic re-render with default style
        self.assertEqual(_render_bytes("K"), base)

        icons.set_style(glow=(255, 220, 120))
        with_glow = _render_bytes("K")
        self.assertNotEqual(base, with_glow)
        icons.set_style(glow=None)
        self.assertEqual(_render_bytes("K"), base)

        icons.set_style(rim=(90, 220, 140))
        self.assertNotEqual(_render_bytes("K"), base)
        icons.set_style(rim=None)
        self.assertEqual(_render_bytes("K"), base)

        icons.set_style(ink=(80, 20, 120))
        self.assertNotEqual(_render_bytes("K"), base)
        icons.set_style(ink=None)
        self.assertEqual(_render_bytes("K"), base)

        icons.set_style(glyph=(255, 240, 170))
        self.assertNotEqual(_render_bytes("K"), base)
        icons.set_style(glyph=None)
        self.assertEqual(_render_bytes("K"), base)

    def test_player_colors_untouched_by_style(self):
        """Styling never rewrites PLAYER_COLORS (identification!)."""
        before = [tuple(c) for c in icons.PLAYER_COLORS]
        icons.set_style(rim=(1, 2, 3), glow=(4, 5, 6),
                        ink=(7, 8, 9), glyph=(10, 11, 12))
        _render_bytes("Q")
        self.assertEqual([tuple(c) for c in icons.PLAYER_COLORS], before)


class TestTombstone(unittest.TestCase):
    """SPEC V4.3: draw_tombstone renders graveyard tiles."""

    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def _render(self, size, pad=40):
        side = size + 2 * pad
        surf = pygame.Surface((side, side), pygame.SRCALPHA)
        icons.draw_tombstone(surf, (side // 2, side // 2), size)
        return surf

    def test_renders_non_blank_at_small_sizes(self):
        """Draws something at cell size 30 (and larger)."""
        for size in (30, 48, 64):
            surf = self._render(size)
            rect = surf.get_bounding_rect()
            self.assertGreater(rect.width, 0,
                               "tombstone at size %d drew nothing" % size)
            # tall enough to actually read as a gravestone
            self.assertGreaterEqual(rect.height, int(size * 0.5))

    def test_deterministic(self):
        """Two identical calls produce identical pixels."""
        a = pygame.image.tobytes(self._render(48), "RGBA")
        b = pygame.image.tobytes(self._render(48), "RGBA")
        self.assertEqual(a, b)

    def test_stays_within_tile(self):
        """All painted pixels stay inside a ~size box around center."""
        for size in (30, 48):
            surf = self._render(size)
            cx = cy = surf.get_width() // 2
            rect = surf.get_bounding_rect()
            m = int(size * 0.55) + 2
            self.assertGreaterEqual(rect.left, cx - m)
            self.assertGreaterEqual(rect.top, cy - m)
            self.assertLessEqual(rect.right, cx + m)
            self.assertLessEqual(rect.bottom, cy + m)


class TestCracks(unittest.TestCase):
    """SPEC V4.3: draw_cracks — deterministic per-cell crack art."""

    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def _render(self, cell, size=40, pad=30, color=(20, 18, 16)):
        side = size * 2 + 2 * pad
        surf = pygame.Surface((side, side), pygame.SRCALPHA)
        icons.draw_cracks(surf, cell, (side // 2, side // 2), size,
                          color=color)
        return surf

    def test_renders_non_blank(self):
        for cell in ((0, 0), (3, -2), (-5, 11)):
            surf = self._render(cell)
            self.assertGreater(surf.get_bounding_rect().width, 0,
                               "cracks for %r drew nothing" % (cell,))

    def test_same_cell_identical_every_call(self):
        """Same seed cell -> pixel-identical cracks on every call."""
        for cell in ((0, 0), (7, -3), (-11, 4)):
            a = pygame.image.tobytes(self._render(cell), "RGBA")
            b = pygame.image.tobytes(self._render(cell), "RGBA")
            self.assertEqual(a, b, "cracks for %r not deterministic"
                             % (cell,))

    def test_independent_of_global_random_state(self):
        """Global random seeding never changes the output, and the global
        random state is not disturbed by drawing."""
        import random as _random
        _random.seed(111)
        a = pygame.image.tobytes(self._render((2, 5)), "RGBA")
        _random.seed(999)
        b = pygame.image.tobytes(self._render((2, 5)), "RGBA")
        self.assertEqual(a, b)
        # drawing must not consume/perturb the global stream
        _random.seed(424242)
        state = _random.getstate()
        self._render((6, -1))
        self.assertEqual(_random.getstate(), state)

    def test_different_cells_differ(self):
        """Distinct seed cells produce distinct crack layouts."""
        base = pygame.image.tobytes(self._render((0, 0)), "RGBA")
        others = [(1, 0), (0, 1), (5, -3), (-4, 9)]
        diffs = sum(
            1 for c in others
            if pygame.image.tobytes(self._render(c), "RGBA") != base)
        self.assertGreaterEqual(diffs, 3)

    def test_stays_within_reach_of_center(self):
        """Every painted pixel lies within ~0.9 * size of center."""
        for cell in ((0, 0), (4, -7), (12, 3)):
            for size in (30, 48):
                surf = self._render(cell, size=size)
                cx = cy = surf.get_width() // 2
                lw = max(1, int(round(size / 14.0)))
                limit = 0.9 * size + lw + 2
                rect = surf.get_bounding_rect()
                self.assertGreaterEqual(rect.left, cx - limit)
                self.assertGreaterEqual(rect.top, cy - limit)
                self.assertLessEqual(rect.right, cx + limit + 1)
                self.assertLessEqual(rect.bottom, cy + limit + 1)


if __name__ == "__main__":
    unittest.main()
