"""Coordinate and validation rules; independent of Blender.

Blender XY corresponds to the game's local XZ; the footprint is centered.
Ports store the *outside connection cell*, and direction is material flow.
"""
import math

DIRECTIONS = {"E": (1, 0), "W": (-1, 0), "N": (0, 1), "S": (0, -1)}


def resize_bitmap(bitmap, old_width, old_length, width, length):
    return "".join(
        bitmap[y * old_width + x]
        if x < old_width and y < old_length and y * old_width + x < len(bitmap)
        else "1"
        for y in range(length) for x in range(width)
    )


def occupied(bitmap, width, length, x, y):
    return (0 <= x < width and 0 <= y < length
            and y * width + x < len(bitmap) and bitmap[y * width + x] == "1")


def cell_at(point, width, length, cell_size):
    x = math.floor(point[0] / cell_size + width / 2)
    y = math.floor(point[1] / cell_size + length / 2)
    return (x, y) if 0 <= x < width and 0 <= y < length else None


def boundary_edges(bitmap, width, length):
    """Yield occupied cell + outward normal, including holes/concave edges."""
    for y in range(length):
        for x in range(width):
            if occupied(bitmap, width, length, x, y):
                for dx, dy in DIRECTIONS.values():
                    if not occupied(bitmap, width, length, x + dx, y + dy):
                        yield x, y, dx, dy


def edge_center(edge, width, length, cell_size):
    x, y, dx, dy = edge
    return ((x + .5 + dx * .5 - width / 2) * cell_size,
            (y + .5 + dy * .5 - length / 2) * cell_size, 0.0)


def port_from_edge(edge, kind):
    x, y, dx, dy = edge
    return x + dx, y + dy, (-dx, -dy) if kind == "Input" else (dx, dy)


def port_edge(x, y, direction, kind):
    dx, dy = direction
    if kind == "Input":
        return x + dx, y + dy, -dx, -dy
    return x - dx, y - dy, dx, dy


def port_error(bitmap, width, length, x, y, direction, kind):
    if occupied(bitmap, width, length, x, y):
        return "连接格必须位于占格之外"
    dx, dy = direction
    sign = 1 if kind == "Input" else -1
    if not occupied(bitmap, width, length, x + sign * dx, y + sign * dy):
        return "端口方向未连接到占用格"
    return ""
