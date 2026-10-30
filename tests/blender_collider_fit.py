"""Background fitting regression: local axes, transforms, modifiers, groups."""
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon
from factory_building import colliders


def select(objects, active=None):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active or objects[0]
    bpy.context.view_layer.update()


def contains(proxy, world):
    v = colliders.rigid_matrix(proxy).inverted() @ world
    p = proxy.factory_collider
    epsilon = 2e-4
    if p.kind == 'BOX':
        return all(abs(v[i]) <= p.size[i] / 2 + epsilon for i in range(3))
    if p.kind == 'SPHERE':
        return v.length <= p.radius + epsilon
    if p.kind == 'CYLINDER':
        return math.hypot(v.x, v.y) <= p.radius + epsilon and abs(v.z) <= p.height / 2 + epsilon
    half_segment = max(0, p.height / 2 - p.radius)
    return Vector((v.x, v.y, max(0, abs(v.z) - half_segment))).length <= p.radius + epsilon


def fit(sources, kind, scope, reference=None):
    select(sources, reference)
    count = len(bpy.data.meshes)
    original = [(obj.matrix_world.copy(), [v.co.copy() for v in obj.data.vertices]) for obj in sources]
    assert bpy.ops.factory.fit_collider(kind=kind, scope=scope) == {'FINISHED'}
    proxies = list(bpy.context.selected_objects)
    assert len(proxies) == (len(sources) if scope == 'EACH' else 1)
    assert len(bpy.data.meshes) == count
    graph = bpy.context.evaluated_depsgraph_get()
    for i, proxy in enumerate(proxies):
        assert colliders.is_proxy(proxy) and proxy.parent is None
        assert tuple(proxy.scale) == (1, 1, 1)
        assert tuple(proxy.lock_scale) == (True, True, True)
        group = [sources[i]] if scope == 'EACH' else sources
        ref = group[0] if scope == 'EACH' else (reference or sources[0])
        expected_rotation = colliders.rigid_matrix(ref.evaluated_get(graph)).to_quaternion()
        assert proxy.rotation_euler.to_quaternion().rotation_difference(expected_rotation).angle < .001
        for obj in group:
            points = colliders.evaluated_points(obj, graph, Matrix.Identity(4))
            assert all(contains(proxy, point) for point in points), (kind, scope, obj.name)
    for obj, (matrix, vertices) in zip(sources, original):
        assert all((obj.matrix_world[i] - matrix[i]).length < 1e-6 for i in range(4))
        assert all((v.co - old).length < 1e-6 for v, old in zip(obj.data.vertices, vertices))
    return proxies


addon.register()
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
bpy.ops.mesh.primitive_cube_add(size=2)
first = bpy.context.object
first.name = 'OffsetRotatedModifiedSource'
for v in first.data.vertices:
    v.co += Vector((.4, -.3, .8))
first.location = (4, -3, 2)
first.rotation_euler = (.4, .2, .9)
first.scale = (1.4, .7, 2.1)
array = first.modifiers.new('Evaluated array', 'ARRAY')
array.count = 2
array.use_relative_offset = False
array.use_constant_offset = True
array.constant_offset_displace = (3.7, 0, 0)
bpy.ops.mesh.primitive_cube_add(size=2, location=(-2, 1, 4))
second = bpy.context.object
second.name = 'NegativeScaledSource'
second.rotation_euler = (.1, 1, -.2)
second.scale = (-.5, 1.3, .7)

for kind, _, _ in colliders.KINDS:
    single = fit([first], kind, 'EACH')[0]
    if kind == 'BOX':
        for actual, expected in zip(single.factory_collider.size, (5.7 * 1.4, 1.4, 4.2)):
            assert abs(actual - expected) < 1e-4, (actual, expected)
    fit([first, second], kind, 'EACH')
    overall = fit([first, second], kind, 'ALL', first)[0]
    before = (tuple(overall.factory_collider.size), overall.factory_collider.radius, overall.factory_collider.height)
    center = overall.location.copy()
    # Applying the same world rotation to the complete selection must not
    # inflate bounds in the active object's local fitting frame.
    turn = Matrix.Rotation(.73, 4, 'Z')
    saved = [obj.matrix_world.copy() for obj in (first, second)]
    for obj, matrix in zip((first, second), saved):
        obj.matrix_world = turn @ matrix
    rotated = fit([first, second], kind, 'ALL', first)[0]
    after = (tuple(rotated.factory_collider.size), rotated.factory_collider.radius, rotated.factory_collider.height)
    assert all(abs(a - b) < 1e-4 for a, b in zip(before[0], after[0]))
    assert abs(before[1] - after[1]) < 1e-4 and abs(before[2] - after[2]) < 1e-4, (kind, before, after)
    assert (rotated.location - turn @ center).length < 1e-4
    for obj, matrix in zip((first, second), saved):
        obj.matrix_world = matrix

# Parent nonuniform scale and child rotation produce shear. The rigid frame
# still generates a legal primitive enclosing every evaluated vertex.
parent = bpy.data.objects.new('Parent', None)
bpy.context.scene.collection.objects.link(parent)
parent.scale = (1.5, .8, 2)
parent.rotation_euler = (.4, .2, .3)
second.parent = parent
for kind, _, _ in colliders.KINDS:
    fit([second], kind, 'EACH')

# Menu structure: exact labels and four shapes, no entries for proxy/empty data.
entries = []
layout = SimpleNamespace(separator=lambda: None, menu=lambda identifier, **kw: entries.append((identifier, kw['text'])))
select([first])
colliders.object_context_menu(SimpleNamespace(layout=layout), bpy.context)
assert entries == [('FACTORY_MT_collider_fit_each', '生成外接几何碰撞代理')]
entries.clear()
select([first, second], first)
colliders.object_context_menu(SimpleNamespace(layout=layout), bpy.context)
assert [text for _, text in entries] == ['生成外接几何碰撞代理（每个）', '生成外接几何碰撞代理（整体）']
shapes = []
layout = SimpleNamespace(operator=lambda identifier, **kw: shapes.append((identifier, kw['text'])) or SimpleNamespace())
colliders.draw_fit_shapes(layout, 'ALL')
assert [text for _, text in shapes] == ['立方体', '球', '圆柱体', '胶囊体']

empty_mesh = bpy.data.meshes.new('No vertices')
empty = bpy.data.objects.new('Invalid source', empty_mesh)
bpy.context.scene.collection.objects.link(empty)
select([first, empty])
count = len(bpy.data.objects)
assert bpy.ops.factory.fit_collider(kind='BOX', scope='EACH') == {'CANCELLED'}
assert len(bpy.data.objects) == count, 'Failed fitting left partial proxies'
addon.unregister()
print('FACTORY_COLLIDER_FIT_TESTS_OK Blender', bpy.app.version_string)
