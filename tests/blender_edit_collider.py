"""Small Blender 4.1 edit-selection regression, optionally including GUI undo."""
from pathlib import Path
import sys
import traceback

import bpy
import bmesh
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon
from factory_building import colliders


def proxies():
    return [o for o in bpy.context.scene.objects if colliders.is_proxy(o)]


def check():
    addon.register()
    bpy.ops.mesh.primitive_cube_add()
    source = bpy.context.object
    source.name = 'EditSelectionSource'
    source.location = (4, -3, 2)
    source.rotation_euler = (.2, .4, .7)
    source.scale = (2, 3, 4)
    # A distant unselected vertex must not inflate the resulting proxy.
    mesh = bmesh.new()
    mesh.from_mesh(source.data)
    mesh.verts.new((100, 100, 100))
    mesh.to_mesh(source.data)
    mesh.free()
    bpy.ops.object.mode_set(mode='EDIT')
    for mode in ('VERT', 'EDGE', 'FACE'):
        bpy.ops.mesh.select_mode(type=mode)
        bpy.ops.mesh.select_all(action='DESELECT')
        bm = bmesh.from_edit_mesh(source.data)
        elements = {'VERT': bm.verts, 'EDGE': bm.edges, 'FACE': bm.faces}[mode]
        elements.ensure_lookup_table()
        elements[0].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(source.data)
        chosen = [v.index for v in bm.verts if v.select and not v.hide]
        world_points = [source.matrix_world @ v.co for v in bm.verts if v.select and not v.hide]
        for kind in (('BOX', 'SPHERE', 'CYLINDER', 'CAPSULE') if mode == 'FACE' else ('BOX',)):
            before = set(proxies())
            assert bpy.ops.factory.fit_selection_collider(kind=kind) == {'FINISHED'}
            assert bpy.context.mode == 'EDIT_MESH' and bpy.context.edit_object == source
            bm = bmesh.from_edit_mesh(source.data)
            assert chosen == [v.index for v in bm.verts if v.select and not v.hide]
            proxy, = set(proxies()) - before
            assert proxy in next(c for c in bpy.context.scene.collection.children
                                 if c.get('factory_collider_collection')).objects.values()
            assert tuple(proxy.scale) == (1, 1, 1)
            assert max(proxy.factory_collider.size) < 30
            bpy.context.view_layer.update()
            inv = colliders.rigid_matrix(proxy).inverted()
            p = proxy.factory_collider
            for point in world_points:
                v = inv @ point
                if kind == 'BOX':
                    assert all(abs(v[i]) <= p.size[i] / 2 + 1e-4 for i in range(3))
                elif kind == 'SPHERE':
                    assert v.length <= p.radius + 1e-4
                else:
                    half = p.height / 2 if kind == 'CYLINDER' else max(0, p.height / 2 - p.radius)
                    assert Vector((v.x, v.y, max(0, abs(v.z) - half))).length <= p.radius + 1e-4
    bpy.ops.mesh.select_all(action='DESELECT')
    count = len(proxies())
    assert bpy.ops.factory.fit_selection_collider() == {'CANCELLED'}
    assert len(proxies()) == count
    bpy.ops.mesh.select_all(action='SELECT')
    if not bpy.app.background:
        bpy.ops.ed.undo_push(message='Before edit proxy')
        bpy.ops.factory.fit_selection_collider(kind='BOX')
        assert len(proxies()) == count + 1
        bpy.ops.factory.fit_selection_collider(kind='SPHERE')
        assert len(proxies()) == count + 2
        bpy.ops.ed.undo()
        assert len(proxies()) == count + 1, 'Edit-mode undo did not remove proxy'
        bpy.ops.ed.redo()
        assert len(proxies()) == count + 2
        bpy.ops.ed.undo()
        bpy.ops.ed.undo()
        assert len(proxies()) == count, 'Repeated undo left an extra step'
    bpy.ops.object.mode_set(mode='OBJECT')
    # Multi-object edit mode must include both selected cages, not just active.
    source = bpy.data.objects['EditSelectionSource']
    bpy.ops.mesh.primitive_cube_add(location=(12, 0, 0))
    second = bpy.context.object
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    for obj in (source, second):
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.verts[0].select_set(True)
        bmesh.update_edit_mesh(obj.data)
    before = set(proxies())
    assert bpy.ops.factory.fit_selection_collider(kind='BOX') == {'FINISHED'}
    assert len(set(proxies()) - before) == 1
    assert set(bpy.context.objects_in_mode) == {source, second}
    bpy.ops.object.mode_set(mode='OBJECT')
    addon.unregister()
    print('FACTORY_EDIT_COLLIDER_OK', bpy.app.version_string)


if bpy.app.background:
    check()
else:
    def run():
        try:
            area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
            region = next(r for r in area.regions if r.type == 'WINDOW')
            with bpy.context.temp_override(area=area, region=region):
                check()
        except Exception:
            traceback.print_exc()
        finally:
            bpy.ops.wm.quit_blender()
    bpy.app.timers.register(run, first_interval=.8)
