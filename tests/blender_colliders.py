"""Background regression: proxy authoring, constraints, picking math and .blend."""
import math
from pathlib import Path
import sys
import tempfile

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon
from factory_building import colliders, collider_geometry as geometry


def close(a, b):
    assert abs(a - b) < 1e-5, (a, b)


addon.register()
scene = bpy.context.scene
scene.cursor.location = (3, 4, 5)
mesh_count = len(bpy.data.meshes)
proxies = []
for kind, _, _ in colliders.KINDS:
    assert bpy.ops.factory.add_collider(kind=kind) == {'FINISHED'}
    obj = bpy.context.object
    proxies.append(obj)
    assert obj.type == 'EMPTY' and obj.data is None and colliders.is_proxy(obj)
    assert obj.factory_collider.kind == kind
    assert tuple(obj.lock_scale) == (True, True, True)
    assert tuple(obj.location) == (3, 4, 5)
    assert obj.hide_render and obj['factory_role'] == 'collider'
assert len(bpy.data.meshes) == mesh_count
assert len({p.users_collection[0].as_pointer() for p in proxies}) == 1

box, sphere, cylinder, capsule = proxies
box.factory_collider.size = (2, 3, 4)
sphere.factory_collider.radius = 1.25
cylinder.factory_collider.radius = .75
cylinder.factory_collider.height = 3
capsule.factory_collider.height = .1
close(capsule.factory_collider.height, 1)
capsule.factory_collider.radius = 2
close(capsule.factory_collider.height, 4)
capsule.factory_collider.height = 6

for obj in proxies:
    p = obj.factory_collider
    vertices, faces, edges = geometry.geometry(p.kind, tuple(p.size), p.radius, p.height)
    assert faces and edges and all(0 <= i < len(vertices) for face in faces for i in face)
    extents = [max(v[axis] for v in vertices) - min(v[axis] for v in vertices) for axis in range(3)]
    expected = tuple(p.size) if p.kind == 'BOX' else (2 * p.radius, 2 * p.radius, 2 * p.radius if p.kind == 'SPHERE' else p.height)
    for actual, target in zip(extents, expected):
        close(actual, target)
    expected_z = expected[2] / 2
    close(geometry.ray_hit(p.kind, (0, 0, 10), (0, 0, -1), tuple(p.size), p.radius, p.height), 10 - expected_z)
    assert geometry.ray_hit(p.kind, (20, 20, 10), (0, 0, -1), tuple(p.size), p.radius, p.height) is None
    # Side, inside, and parallel rays must remain valid for each primitive.
    assert geometry.ray_hit(p.kind, (10, 0, 0), (-1, 0, 0), tuple(p.size), p.radius, p.height) is not None
    assert geometry.ray_hit(p.kind, (0, 0, 0), (1, 0, 0), tuple(p.size), p.radius, p.height) is not None

box.location = (1, 2, 3)
box.rotation_euler = (0, 0, math.pi / 2)
bpy.context.view_layer.update()
assert (colliders.rigid_matrix(box) @ Vector((1, 0, 0)) - Vector((1, 3, 3))).length < 1e-5
box.scale = (2, 3, 4)  # Script bypass of transform locks is detected, never deforms geometry.
bpy.context.view_layer.update()
assert colliders.scale_error(box)
assert (colliders.rigid_matrix(box) @ Vector((1, 0, 0)) - Vector((1, 3, 3))).length < 1e-5
box.scale = (1, 1, 1)
bpy.context.view_layer.update()

# Native duplication creates an independent parameter group, not shared mesh data.
for obj in bpy.context.selected_objects:
    obj.select_set(False)
capsule.select_set(True)
bpy.context.view_layer.objects.active = capsule
bpy.ops.object.duplicate()
duplicate = bpy.context.object
assert duplicate != capsule and duplicate.data is None
duplicate.factory_collider.radius = .25
close(capsule.factory_collider.radius, 2)
bpy.ops.object.delete()
assert len(bpy.data.meshes) == mesh_count

with tempfile.TemporaryDirectory(prefix='factory-colliders-') as directory:
    path = str(Path(directory) / 'proxies.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    bpy.ops.wm.open_mainfile(filepath=path)
    restored = [o for o in bpy.context.scene.objects if colliders.is_proxy(o)]
    assert len(restored) == 4
    restored_capsule = next(o for o in restored if o.factory_collider.kind == 'CAPSULE')
    close(restored_capsule.factory_collider.radius, 2)
    close(restored_capsule.factory_collider.height, 6)
    assert all(o.data is None and tuple(o.lock_scale) == (True, True, True) for o in restored)
addon.unregister()
assert not colliders._handles and not colliders._keymaps
addon.register()
assert len(colliders._handles) == 1
addon.unregister()
print('FACTORY_COLLIDER_TESTS_OK Blender', bpy.app.version_string)
