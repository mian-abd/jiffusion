from collections import deque
import unittest

from generate_shapes import SHAPES, STYLES, VARIANTS, render_shape
from image_to_ascii import to_ascii
from prompts import PALETTE


def connected_components(points, diagonal=False):
    remaining = set(points)
    groups = []
    offsets = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
               if (dy or dx) and (diagonal or abs(dy) + abs(dx) == 1)]
    while remaining:
        start = remaining.pop()
        group, queue = {start}, deque([start])
        while queue:
            y, x = queue.popleft()
            for dy, dx in offsets:
                neighbor = (y + dy, x + dx)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    group.add(neighbor)
                    queue.append(neighbor)
        groups.append(group)
    return groups


class ShapeDatasetTests(unittest.TestCase):
    def test_quantized_shapes_remain_connected_with_the_intended_holes(self):
        canvas = {(y, x) for y in range(20) for x in range(20)}
        for shape in SHAPES:
            for style in STYLES:
                for variant in VARIANTS:
                    with self.subTest(shape=shape, style=style, variant=variant['name']):
                        rows = to_ascii(render_shape(shape, style, variant)).splitlines()
                        negative = style.startswith('negative')
                        foreground = {(y, x) for y, x in canvas
                                      if (PALETTE.index(rows[y][x]) <= 2 if negative
                                          else PALETTE.index(rows[y][x]) >= 2)}
                        self.assertEqual(len(connected_components(foreground, diagonal=True)), 1)
                        holes = [group for group in connected_components(canvas - foreground)
                                 if not any(y in (0, 19) or x in (0, 19) for y, x in group)]
                        self.assertEqual(len(holes), int(style in ('outline', 'negative-outline', 'hole')))


if __name__ == '__main__':
    unittest.main()
