"""Blender 4.1 --factory-startup --enable-event-simulate --python this_file."""
import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector
from bpy_extras import view3d_utils

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon

OUT = ROOT / 'test-results' / 'shortcuts-result.json'


def checked(fn):
    def call():
        try:
            fn()
        except Exception:
            error = traceback.format_exc()
            print(error)
            OUT.write_text(json.dumps({'ok': False, 'error': error}), encoding='utf8')
            bpy.ops.wm.quit_blender()
    return call


def send(kind, value='PRESS', alt=False, world=(0, 0, 0)):
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, Vector(world))
    bpy.context.window.event_simulate(type=kind, value=value, alt=alt,
        x=int(region.x + point.x), y=int(region.y + point.y))


def shortcut(key):
    send('MOUSEMOVE', 'NOTHING')
    send(key, alt=True)
    send(key, 'RELEASE', alt=True)


@checked
def start():
    addon.register()
    assert len(addon._keymaps) == 5
    bpy.context.window.event_simulate(type='ESC', value='PRESS')
    bpy.ops.mesh.primitive_cube_add()
    bpy.context.object.scale = (2, 2, 2)
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    area.spaces.active.region_3d.view_rotation = Quaternion((1, 0, 0, 0))
    area.spaces.active.region_3d.view_perspective = 'ORTHO'
    area.spaces.active.region_3d.view_location = (0, 0, 0)
    area.spaces.active.region_3d.view_distance = 9
    area.tag_redraw()
    bpy.app.timers.register(enter_cells, first_interval=.5)


@checked
def enter_cells():
    shortcut('S')
    bpy.app.timers.register(switch_ports, first_interval=.4)


@checked
def switch_ports():
    assert addon._session and addon._session.mode == 'CELLS', 'Alt+S did not enter cells'
    assert tuple(bpy.context.object.scale) == (2, 2, 2), 'Default clear-scale binding ran'
    shortcut('F')
    bpy.app.timers.register(edit_port, first_interval=.4)


@checked
def edit_port():
    assert addon._session and addon._session.mode == 'PORTS', 'Alt+F did not switch modes'
    send('LEFTMOUSE', world=(-2, -1, 0))
    send('LEFTMOUSE', 'RELEASE', world=(-2, -1, 0))
    bpy.app.timers.register(switch_cells, first_interval=.3)


@checked
def switch_cells():
    assert len(bpy.context.scene.factory_building.ports) == 1
    shortcut('S')
    bpy.app.timers.register(exit_and_enter_ports, first_interval=.3)


@checked
def exit_and_enter_ports():
    assert addon._session and addon._session.mode == 'CELLS'
    send('ESC')
    bpy.app.timers.register(enter_ports, first_interval=.3)


@checked
def enter_ports():
    assert addon._session is None
    shortcut('F')
    bpy.app.timers.register(finish, first_interval=.3)


@checked
def finish():
    assert addon._session and addon._session.mode == 'PORTS', 'Alt+F did not enter from idle'
    addon.unregister()
    assert not addon._keymaps
    addon.register()
    assert len(addon._keymaps) == 5
    addon.unregister()
    assert not addon._keymaps
    OUT.write_text(json.dumps({'ok': True, 'blender': bpy.app.version_string,
        'checks': ['Alt+S enters cells', 'Alt+F enters ports', 'switch both ways',
                   'default clear-scale suppressed', 'keymaps removed and re-registered']}), encoding='utf8')
    print('FACTORY_SHORTCUT_TESTS_OK')
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(start, first_interval=.5)
