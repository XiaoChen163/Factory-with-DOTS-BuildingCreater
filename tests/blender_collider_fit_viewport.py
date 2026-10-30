"""GUI regression for selection-dependent fitting menus and fitted proxy undo."""
import json
from pathlib import Path
import sys
import traceback

import bpy
from mathutils import Euler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon
from factory_building import colliders

OUT = ROOT / 'test-results'
seen = []


def checked(fn):
    def call():
        try:
            fn()
        except Exception:
            error = traceback.format_exc()
            print(error)
            (OUT / 'collider-fit-viewport-result.json').write_text(json.dumps({'ok': False, 'error': error}), encoding='utf8')
            bpy.ops.wm.quit_blender()
    return call


def surface():
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def select(names):
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for name in names:
        bpy.data.objects[name].select_set(True)
    bpy.context.view_layer.objects.active = bpy.data.objects[names[0]]
    bpy.context.view_layer.update()


def observe(self, context):
    seen.append(len(colliders.fit_sources(context)))


def right_click():
    area, region = surface()
    for kind, value in [('MOUSEMOVE', 'NOTHING'), ('RIGHTMOUSE', 'PRESS'), ('RIGHTMOUSE', 'RELEASE')]:
        bpy.context.window.event_simulate(type=kind, value=value,
            x=region.x + region.width // 2, y=region.y + region.height // 2)


def escape():
    bpy.context.window.event_simulate(type='ESC', value='PRESS')


@checked
def start():
    addon.FACTORY_PT_footprint.bl_options = {'DEFAULT_CLOSED'}
    addon.FACTORY_PT_ports.bl_options = {'DEFAULT_CLOSED'}
    addon.register()
    escape()
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.scene.factory_building.visible = False
    bpy.context.scene.factory_building.render_layer = 'FRONT'
    bpy.ops.mesh.primitive_cube_add(size=2)
    first = bpy.context.object
    first.name = 'FitSourceA'
    first.rotation_euler = (.1, .2, .5)
    first.scale = (1.5, .6, 1.2)
    bpy.ops.mesh.primitive_cube_add(size=2, location=(3, 1, 1))
    second = bpy.context.object
    second.name = 'FitSourceB'
    second.scale = (.5, .8, .7)
    select(['FitSourceA'])
    area, region = surface()
    area.spaces.active.show_region_ui = True
    rv = area.spaces.active.region_3d
    rv.view_rotation = Euler((.9, 0, .4)).to_quaternion()
    rv.view_distance = 13
    rv.view_location = (1, 0, 0)
    bpy.types.VIEW3D_MT_object_context_menu.append(observe)
    area.tag_redraw()
    bpy.app.timers.register(single_menu, first_interval=.5)


@checked
def single_menu():
    right_click()
    bpy.app.timers.register(single_fit, first_interval=.4)


@checked
def single_fit():
    assert 1 in seen, 'Single-selection right-click menu not drawn'
    bpy.ops.screen.screenshot(filepath=str(OUT / 'fit-single-context-menu.png'))
    escape()
    bpy.app.timers.register(do_single_fit, first_interval=.2)


@checked
def do_single_fit():
    area, region = surface()
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.ed.undo_push(message='Before fitted proxy')
        assert bpy.ops.factory.fit_collider('INVOKE_DEFAULT', kind='BOX', scope='EACH') == {'FINISHED'}
        proxy = bpy.context.object
        assert all(abs(a - b) < 1e-5 for a, b in zip(proxy.factory_collider.size, (3, 1.2, 2.4)))
        assert proxy.type == 'EMPTY'
        bpy.ops.ed.undo_push(message='After fitted proxy')
        bpy.ops.ed.undo()
        assert len([o for o in bpy.context.scene.objects if colliders.is_proxy(o)]) == 0
        bpy.ops.ed.redo()
        assert len([o for o in bpy.context.scene.objects if colliders.is_proxy(o)]) == 1
    select(['FitSourceA', 'FitSourceB'])
    bpy.app.timers.register(group_menu, first_interval=.3)


@checked
def group_menu():
    right_click()
    bpy.app.timers.register(group_fit, first_interval=.4)


@checked
def group_fit():
    assert 2 in seen, 'Multi-selection right-click menu not drawn'
    bpy.ops.screen.screenshot(filepath=str(OUT / 'fit-group-context-menu.png'))
    escape()
    bpy.app.timers.register(do_group_fit, first_interval=.2)


@checked
def do_group_fit():
    area, region = surface()
    with bpy.context.temp_override(area=area, region=region):
        assert bpy.ops.factory.fit_collider('INVOKE_DEFAULT', kind='CAPSULE', scope='ALL') == {'FINISHED'}
    assert len(bpy.context.selected_objects) == 1
    proxy = bpy.context.object
    assert proxy.factory_collider.kind == 'CAPSULE'
    assert proxy.factory_collider.height >= 2 * proxy.factory_collider.radius
    assert tuple(proxy.scale) == (1, 1, 1)
    assert proxy.rotation_euler.to_quaternion().rotation_difference(bpy.data.objects['FitSourceA'].rotation_euler.to_quaternion()).angle < .001
    area.tag_redraw()
    bpy.app.timers.register(finish, first_interval=.4)


@checked
def finish():
    bpy.ops.screen.screenshot(filepath=str(OUT / 'blender-4.1-fitted-colliders.png'))
    (OUT / 'collider-fit-viewport-result.json').write_text(json.dumps({'ok': True, 'blender': bpy.app.version_string,
        'checks': ['single right-click menu', 'multi right-click menu', 'local box dimensions',
                   'fitted proxy undo/redo', 'group capsule generation']}), encoding='utf8')
    bpy.types.VIEW3D_MT_object_context_menu.remove(observe)
    addon.unregister()
    print('FACTORY_COLLIDER_FIT_VIEWPORT_TESTS_OK')
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(start, first_interval=.5)
