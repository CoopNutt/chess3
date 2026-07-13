"""Generates chess3.ico for the exe build (dragon on a hex)."""
import os
import math

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame

import icons


def make(path="chess3.ico"):
    pygame.init()
    size = 256
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size // 2
    pts = [(c + c * 0.96 * math.cos(math.radians(60 * k - 30)),
            c + c * 0.96 * math.sin(math.radians(60 * k - 30))) for k in range(6)]
    pygame.draw.polygon(surf, (36, 39, 48), pts)
    pygame.draw.polygon(surf, (110, 180, 255), pts, 8)
    icons.draw_piece(surf, "DR", (214, 74, 74), int(size * 0.62), (c, c))
    png = path.replace(".ico", ".png")
    pygame.image.save(surf, png)
    try:
        from PIL import Image
        img = Image.open(png)
        img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        print("wrote", path)
    except ImportError:
        print("Pillow not available; only wrote", png)
    pygame.quit()


if __name__ == "__main__":
    make()
