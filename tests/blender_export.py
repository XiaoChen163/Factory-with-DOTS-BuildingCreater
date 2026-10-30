"""Background end-to-end export and Unity coordinate contract regression."""
import json
import itertools
import math
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import bpy
from mathutils import Matrix, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon
from factory_building import colliders, exporter


def invalid():
    try:
        exporter.build_document(bpy.context)
    except exporter.ExportValidationError:
        return
    raise AssertionError('Invalid metadata was accepted')


addon.register()
assert not exporter.FACTORY_OT_export.poll(bpy.context), 'Unsaved projects must be rejected'
invalid()
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
s = bpy.context.scene.factory_building
s.bitmap = '111111111100'
bpy.ops.factory.add_port(edge=6, dx=0, dy=1)
bpy.ops.factory.add_port(edge=7, dx=1, dy=0)
bpy.ops.factory.reverse_port()
proxies = []
for kind, _, _ in colliders.KINDS:
    bpy.ops.factory.add_collider(kind=kind)
    obj = bpy.context.object
    obj.location = (1, 2, 3)
    obj.rotation_euler = (.3, -.7, 1.1)
    proxies.append(obj)
proxies[0].factory_collider.size = (2, 3, 4)
proxies[2].factory_collider.height = 3
proxies[3].factory_collider.height = 4
proxies[3].hide_set(True)  # Display state never decides what is exported.

with tempfile.TemporaryDirectory(prefix='factory-export-') as directory:
    blend = Path(directory) / '测试建筑.Model.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    path = blend.with_suffix('.factory.json')
    assert exporter.export_path() == path
    assert exporter.FACTORY_OT_export.poll(bpy.context)
    assert bpy.ops.factory.export_json() == {'FINISHED'}
    raw = path.read_bytes()
    data = json.loads(raw.decode('utf-8'))
    assert not raw.startswith(b'\xef\xbb\xbf') and b'\r\n' not in raw
    assert data['schema_version'] == 1
    assert data['building'] == {'key': '测试建筑.Model', 'model_file': '测试建筑.Model.fbx',
        'width': 4, 'length': 3, 'is_rectangle': False, 'bitmap': '1111/1111/1100'}
    assert data['coordinates']['blender_to_unity'] == [[1, 0, 0], [0, 0, 1], [0, 1, 0]]
    assert data['ports'][0] == {'type': 'Input', 'index': 0, 'cell_x': 2, 'cell_z': 2,
                                'direction_x': 0, 'direction_z': -1}
    assert data['ports'][1]['output_slot'] == 1 and data['ports'][1]['number'] == 1
    assert [p['name'] for p in data['colliders']] == sorted(o.name for o in proxies)
    assert len(data['colliders']) == 4
    # All seven useful combinations; omitted sections must not mean clear-all.
    for footprint, ports, shapes in itertools.product((False, True), repeat=3):
        if not any((footprint, ports, shapes)):
            try:
                exporter.build_document(bpy.context, False, False, False)
            except exporter.ExportValidationError:
                pass
            else:
                raise AssertionError('Empty selection was accepted')
            continue
        partial = exporter.build_document(bpy.context, footprint, ports, shapes)
        assert ('width' in partial['building']) == footprint
        assert ('ports' in partial) == ports
        assert ('colliders' in partial) == shapes
        (ROOT / 'test-results' / ('export-selection-%d%d%d.json' % (footprint, ports, shapes))).write_text(
            json.dumps(partial, ensure_ascii=False), encoding='utf8')
    custom = Path(directory) / '自选位置'
    custom.mkdir()
    target = custom / 'Custom.factory.json'
    assert bpy.ops.factory.export_json(filepath=str(target), export_ports=False) == {'FINISHED'}
    assert 'ports' not in json.loads(target.read_text(encoding='utf8'))
    for obj in proxies:
        record = next(c for c in data['colliders'] if c['name'] == obj.name)
        assert record['position'] == {'x': 1.0, 'y': 3.0, 'z': 2.0}
        q = record['rotation']
        rotation = Quaternion((q['w'], q['x'], q['y'], q['z']))
        assert abs(rotation.magnitude - 1) < 1e-5
        # Basis-conjugated quaternion rotates mapped vertices identically.
        original = obj.matrix_world.to_quaternion()
        for direction in (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))):
            assert (rotation @ (exporter.AXIS_CHANGE @ direction) - exporter.AXIS_CHANGE @ (original @ direction)).length < 1e-5
        if record['type'] == 'Box':
            assert record['size'] == {'x': 2.0, 'y': 4.0, 'z': 3.0}
        if record['type'] in {'Cylinder', 'Capsule'}:
            assert record['axis'] == 'Y'
    # Idempotent export (no timestamps, absolute paths, or UI state).
    s.visible = False
    s.render_layer = 'FRONT'
    bpy.context.scene.factory_collider_display = False
    assert bpy.ops.factory.export_json() == {'FINISHED'}
    assert path.read_bytes() == raw
    # Scene metric display settings do not rescale one-unit grid data.
    bpy.context.scene.unit_settings.scale_length = .01
    assert exporter.build_document(bpy.context) == data

    # Parent rotation/translation are baked into a Unity-local pose.
    parent = bpy.data.objects.new('Parent', None)
    bpy.context.scene.collection.objects.link(parent)
    parent.location = (5, 6, 7)
    parent.rotation_euler.z = math.pi / 2
    box = proxies[0]
    box.parent = parent
    baked = exporter.build_document(bpy.context)
    position = next(c for c in baked['colliders'] if c['name'] == box.name)['position']
    assert all(abs(a - b) < 1e-5 for a, b in zip(position.values(), (3, 10, 7)))
    parent.scale = (2, 1, 1)
    invalid()
    parent.scale = (1, 1, 1)
    box.parent = None
    box.scale = (2, 1, 1)
    invalid()
    assert 'colliders' not in exporter.build_document(bpy.context, export_colliders=False)
    assert bpy.ops.factory.export_json() == {'CANCELLED'}
    assert path.read_bytes() == raw, 'Validation failure overwrote the last valid export'
    box.scale = (1, 1, 1)
    box.scale = (-1, -1, 1)
    invalid()
    box.scale = (1, 1, 1)
    box.delta_scale = (1, 2, 1)
    invalid()
    box.delta_scale = (1, 1, 1)
    # Reject malformed bitmap, empty footprint, invalid ports and stale indices.
    original = s.bitmap
    s.bitmap = '1'
    invalid()
    s.bitmap = '0' * 12
    invalid()
    assert len(exporter.build_document(bpy.context, False, False, True)['colliders']) == 4
    s.bitmap = original
    s.ports[0].cell_x = 0
    s.ports[0].cell_z = 0
    invalid()
    assert 'ports' not in exporter.build_document(bpy.context, export_ports=False)
    s.ports[0].cell_x, s.ports[0].cell_z = 2, 2
    s.ports[0].index = 256
    invalid()
    s.ports[0].index = 3
    invalid()
    s.ports[0].index = 0
    box['factory_role'] = 'collider'
    box.factory_collider.kind = 'NONE'
    invalid()
    box.factory_collider.kind = 'BOX'
    proxies[3].factory_collider['height'] = .1
    invalid()
    proxies[3].factory_collider.height = 4
    box.factory_collider['radius'] = float('nan')  # Unused box radius is not serialized.
    exporter.build_document(bpy.context)
    proxies[1].factory_collider['radius'] = float('nan')
    invalid()
    proxies[1].factory_collider.radius = .5
    # No half-written output or temporary files if replacement fails.
    with patch.object(exporter.os, 'replace', side_effect=OSError('Simulated locked target')):
        try:
            exporter.write_document(path, data)
        except OSError:
            pass
        else:
            raise AssertionError('Replace failure was swallowed')
    assert path.read_bytes() == raw
    assert not list(path.parent.glob('*.tmp'))
    # Rectangle canonical form is compatible with the project's CSV importer.
    s.bitmap = '1' * 12
    s.ports.clear()
    rectangular = exporter.build_document(bpy.context)
    assert rectangular['building']['is_rectangle'] and rectangular['building']['bitmap'] == ''
    # Only this scene's proxies are included, even when objects are hidden.
    second_scene = bpy.data.scenes.new('Other scene')
    other = bpy.data.objects.new('OtherSceneProxy', None)
    second_scene.collection.objects.link(other)
    other.factory_collider.kind = 'BOX'
    assert len(exporter.build_document(bpy.context)['colliders']) == 4
    # Example is a data contract artifact, not a user's .blend/project asset.
    example = ROOT / 'examples' / '测试建筑.Model.factory.json'
    example.parent.mkdir(exist_ok=True)
    exporter.write_document(example, data)
addon.unregister()
addon.register()
addon.unregister()
print('FACTORY_EXPORT_TESTS_OK Blender', bpy.app.version_string)
