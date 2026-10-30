"""Real GUI regression: Empty proxy picking, native transforms and GPU drawing."""
import json
import math
from pathlib import Path
import sys
import traceback

import bpy
from bpy_extras import view3d_utils
from mathutils import Euler, Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon
from factory_building import colliders

OUT = ROOT / 'test-results'
names = []
menu_draws = []


def checked(fn):
    def call():
        try:
            fn()
        except Exception:
            error = traceback.format_exc()
            print(error)
            (OUT / 'collider-viewport-result.json').write_text(json.dumps({'ok': False, 'error': error}), encoding='utf8')
            bpy.ops.screen.screenshot(filepath=str(OUT / 'collider-failure.png'))
            bpy.ops.wm.quit_blender()
    return call


def surface():
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    return area, next(r for r in area.regions if r.type == 'WINDOW')


def send(key, value='PRESS', *, world=(-2.65, 0, 1), shift=False, unicode=''):
    area, region = surface()
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, Vector(world))
    extra = {'unicode': unicode} if unicode else {}
    bpy.context.window.event_simulate(type=key, value=value, shift=shift,
        x=int(region.x + point.x), y=int(region.y + point.y), **extra)


def click(world):
    for key, value in [('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')]:
        send(key, value, world=world)


def observe_menu(self, context):
    menu_draws.append(True)


@checked
def start():
    addon.FACTORY_PT_footprint.bl_options = {'DEFAULT_CLOSED'}
    addon.FACTORY_PT_ports.bl_options = {'DEFAULT_CLOSED'}
    addon.register()
    bpy.context.window.event_simulate(type='ESC', value='PRESS')
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.scene.factory_building.visible = False
    for i, (kind, _, _) in enumerate(colliders.KINDS):
        bpy.context.scene.cursor.location = (i * 2 - 3, 0, 1)
        bpy.ops.factory.add_collider(kind=kind)
        names.append(bpy.context.object.name)
    bpy.data.objects[names[0]].factory_collider.size = (1, 1.5, 2)
    area, region = surface()
    area.spaces.active.show_region_ui = True
    rv = area.spaces.active.region_3d
    rv.view_rotation = Quaternion((1, 0, 0, 0))
    rv.view_perspective = 'ORTHO'
    rv.view_distance = 14
    rv.view_location = (0, 0, 0)
    area.tag_redraw()
    bpy.types.FACTORY_MT_colliders.append(observe_menu)
    bpy.app.timers.register(menu_test, first_interval=.5)


@checked
def menu_test():
    area, region = surface()
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.wm.call_menu(name='FACTORY_MT_colliders')
    bpy.app.timers.register(close_menu, first_interval=.3)


@checked
def close_menu():
    assert menu_draws
    send('ESC')
    bpy.app.timers.register(pick_box, first_interval=.2)


@checked
def pick_box():
    # Click away from the tiny native Empty axes: custom shape picking is needed.
    click((-2.65, 0, 1))
    bpy.app.timers.register(check_box, first_interval=.3)


@checked
def check_box():
    assert bpy.context.object.name == names[0], 'Proxy surface selection failed'
    assert len(bpy.context.selected_objects) == 1
    send('TAB')
    send('TAB', 'RELEASE')
    bpy.app.timers.register(move_box, first_interval=.3)


@checked
def move_box():
    assert bpy.context.mode == 'OBJECT', 'Proxy entered mesh edit mode'
    send('S')
    send('TWO', unicode='2')
    send('RET')
    bpy.app.timers.register(check_scale, first_interval=.3)


@checked
def check_scale():
    assert tuple(bpy.context.object.scale) == (1, 1, 1), 'Native scale bypassed locks'
    assert tuple(bpy.context.object.factory_collider.size) == (1, 1.5, 2)
    send('G')
    send('Y')
    send('TWO', unicode='2')
    send('RET')
    bpy.app.timers.register(rotate_box, first_interval=.3)


@checked
def rotate_box():
    assert abs(bpy.context.object.location.y - 2) < 1e-4, 'Native G move failed'
    send('R')
    send('Z')
    send('NINE', unicode='9')
    send('ZERO', unicode='0')
    send('RET')
    bpy.app.timers.register(duplicate_box, first_interval=.3)


@checked
def duplicate_box():
    assert abs(bpy.context.object.rotation_euler.z - math.pi / 2) < 1e-4, 'Native R rotate failed'
    send('D', shift=True)
    send('ESC')
    bpy.app.timers.register(delete_duplicate, first_interval=.3)


@checked
def delete_duplicate():
    assert len([o for o in bpy.context.scene.objects if colliders.is_proxy(o)]) == 5
    assert bpy.context.object.name != names[0]
    bpy.context.object.factory_collider.size[0] = 2
    assert bpy.data.objects[names[0]].factory_collider.size[0] == 1
    send('DEL')
    send('RET')
    bpy.app.timers.register(native_selection, first_interval=.3)


@checked
def native_selection():
    assert len([o for o in bpy.context.scene.objects if colliders.is_proxy(o)]) == 4
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 3, .5))
    cube = bpy.context.object
    cube.name = 'SelectionFallback'
    bpy.context.view_layer.objects.active = bpy.data.objects[names[0]]
    cube.select_set(False)
    click((0, 3, 1))
    bpy.app.timers.register(occlusion_and_draw, first_interval=.3)


@checked
def occlusion_and_draw():
    assert bpy.context.object.name == 'SelectionFallback', 'Native object selection was intercepted'
    cube = bpy.context.object
    cube.location = (-1, 0, 1)
    cube.scale = (2, 2, 3)
    bpy.context.view_layer.update()
    area, region = surface()
    with bpy.context.temp_override(area=area, region=region):
        mouse = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, Vector((-1, 0, 1)))
        bpy.context.scene.factory_building.render_layer = 'NORMAL'
        assert colliders.pick_proxy(bpy.context, mouse) is None
        bpy.context.scene.factory_building.render_layer = 'FRONT'
        assert colliders.pick_proxy(bpy.context, mouse).name == names[1]
        colliders.draw_proxies()
    cube.hide_set(True)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    capsule = bpy.data.objects[names[3]]
    capsule.select_set(True)
    bpy.context.view_layer.objects.active = capsule
    capsule.factory_collider.height = 2.5
    capsule.rotation_euler.y = -.3
    area.spaces.active.region_3d.view_rotation = Euler((.9, 0, .4)).to_quaternion()
    area.spaces.active.region_3d.view_location = (0, .5, 1)
    area.tag_redraw()
    bpy.app.timers.register(capture, first_interval=.4)


@checked
def capture():
    # Activate the plugin category on this standard test layout.
    area, region = surface()
    ui = next(r for r in area.regions if r.type == 'UI')
    for key, value in [('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')]:
        bpy.context.window.event_simulate(type=key, value=value,
            x=ui.x + ui.width - 12, y=ui.y + ui.height - 225)
    bpy.app.timers.register(finish, first_interval=.4)


@checked
def finish():
    bpy.ops.screen.screenshot(filepath=str(OUT / 'blender-4.1-colliders.png'))
    (OUT / 'collider-viewport-result.json').write_text(json.dumps({'ok': True, 'blender': bpy.app.version_string,
        'checks': ['creation menu', 'shape surface selection', 'no mesh edit mode', 'scale locks',
                   'native G/R', 'native Shift+D/Delete', 'independent parameters', 'native selection fallback',
                   'depth-aware picking', 'GPU drawing']}), encoding='utf8')
    bpy.types.FACTORY_MT_colliders.remove(observe_menu)
    addon.unregister()
    print('FACTORY_COLLIDER_VIEWPORT_TESTS_OK')
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(start, first_interval=.5)
