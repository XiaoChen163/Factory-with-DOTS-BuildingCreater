"""Pure parameterized proxy geometry and analytic picking (local Z is up)."""
from functools import lru_cache
import math


def fit_points(kind, points):
    """Enclose vertices in a caller-chosen orthonormal frame; Z is the axis.

    The bounding-box midpoint is deterministic (not a minimum-volume solver).
    Capsule length is solved from distance to its central line segment, so end
    vertices are enclosed by the hemispheres rather than clipped by them.
    """
    if not points:
        raise ValueError('所选物体没有可拟合的几何顶点')
    lower = tuple(min(p[i] for p in points) for i in range(3))
    upper = tuple(max(p[i] for p in points) for i in range(3))
    center = tuple((a + b) / 2 for a, b in zip(lower, upper))
    local = [tuple(p[i] - center[i] for i in range(3)) for p in points]
    if kind == 'BOX':
        return center, {'size': tuple(max(.001, b - a) for a, b in zip(lower, upper))}
    if kind == 'SPHERE':
        radius = max(.001, math.sqrt(max(sum(v * v for v in p) for p in local)) * (1 + 1e-7))
        return center, {'radius': radius}
    radius = max(.001, math.sqrt(max(x * x + y * y for x, y, _ in local)) * (1 + 1e-7))
    if kind == 'CYLINDER':
        return center, {'radius': radius, 'height': max(.002, upper[2] - lower[2])}
    if kind == 'CAPSULE':
        # Near the cylinder wall, sqrt amplifies float32 transform noise.
        # Treat negligible slack as zero; this is conservative and keeps the
        # fitted height stable under a shared world rotation.
        def allowance(x, y):
            slack = radius * radius - x * x - y * y
            return 0 if slack <= radius * radius * 1e-6 else math.sqrt(slack)
        half_segment = max(0, max(abs(z) - allowance(x, y) for x, y, z in local))
        return center, {'radius': radius, 'height': 2 * (half_segment + radius)}
    raise ValueError(kind)


@lru_cache(maxsize=128)
def geometry(kind, size, radius, height):
    if kind == 'BOX':
        x, y, z = (v / 2 for v in size)
        vertices = ((-x, -y, -z), (x, -y, -z), (x, y, -z), (-x, y, -z),
                    (-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z))
        faces = ((0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
                 (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
                 (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7))
        edges = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6),
                 (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))
        return vertices, faces, edges
    n = 32
    if kind == 'CYLINDER':
        profile = [(0, -height / 2), (radius, -height / 2),
                   (radius, height / 2), (0, height / 2)]
    elif kind == 'SPHERE':
        profile = [(radius * math.cos(i * math.pi / 16), radius * math.sin(i * math.pi / 16))
                   for i in range(-8, 9)]
    elif kind == 'CAPSULE':
        offset = max(0, height / 2 - radius)
        profile = [(radius * math.cos(i * math.pi / 16), radius * math.sin(i * math.pi / 16) - offset)
                   for i in range(-8, 1)]
        profile += [(radius * math.cos(i * math.pi / 16), radius * math.sin(i * math.pi / 16) + offset)
                    for i in range(0, 9)]
    else:
        raise ValueError(kind)
    vertices = tuple((r * math.cos(i * 2 * math.pi / n), r * math.sin(i * 2 * math.pi / n), z)
                     for r, z in profile for i in range(n))
    faces, edges = [], []
    for row in range(len(profile)):
        for i in range(n):
            a, b = row * n + i, row * n + (i + 1) % n
            if row % 4 == 0 or kind == 'CYLINDER' or (kind == 'CAPSULE' and row in (8, 9)):
                edges.append((a, b))
            if row + 1 < len(profile):
                c, d = a + n, b + n
                faces.extend(((a, b, d), (a, d, c)))
                if i % 4 == 0:
                    edges.append((a, c))
    return vertices, tuple(faces), tuple(edges)


def _roots(a, b, c):
    discriminant = b * b - 4 * a * c
    if abs(a) < 1e-12 or discriminant < 0:
        return ()
    root = math.sqrt(max(0, discriminant))
    return ((-b - root) / (2 * a), (-b + root) / (2 * a))


def ray_hit(kind, origin, direction, size, radius, height):
    """Nearest positive local ray distance; callers use a rigid transform."""
    ox, oy, oz = origin
    dx, dy, dz = direction
    if kind == 'BOX':
        lower, upper = -math.inf, math.inf
        for o, d, extent in zip(origin, direction, size):
            half = extent / 2
            if abs(d) < 1e-12:
                if abs(o) > half:
                    return None
            else:
                a, b = sorted(((-half - o) / d, (half - o) / d))
                lower, upper = max(lower, a), min(upper, b)
        if lower > upper or upper < 0:
            return None
        return max(0, lower)
    hits = []
    if kind in {'CYLINDER', 'CAPSULE'}:
        half = height / 2 if kind == 'CYLINDER' else max(0, height / 2 - radius)
        for t in _roots(dx * dx + dy * dy, 2 * (ox * dx + oy * dy), ox * ox + oy * oy - radius * radius):
            if t >= 0 and abs(oz + t * dz) <= half:
                hits.append(t)
        if kind == 'CYLINDER' and abs(dz) > 1e-12:
            for z in (-half, half):
                t = (z - oz) / dz
                if t >= 0 and (ox + t * dx) ** 2 + (oy + t * dy) ** 2 <= radius * radius:
                    hits.append(t)
    if kind in {'SPHERE', 'CAPSULE'}:
        offset = 0 if kind == 'SPHERE' else max(0, height / 2 - radius)
        for sign in ((1,) if kind == 'SPHERE' else (-1, 1)):
            z = oz - sign * offset
            for t in _roots(dx * dx + dy * dy + dz * dz,
                            2 * (ox * dx + oy * dy + z * dz), ox * ox + oy * oy + z * z - radius * radius):
                if t >= 0 and (kind == 'SPHERE' or sign * (oz + t * dz) >= offset - 1e-7):
                    hits.append(t)
    return min(hits) if hits else None
