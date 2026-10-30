"""Real Blender event regression: edit after native orbit/pan consumes MMB release.

Run a separate Blender 4.1 process with --factory-startup --enable-event-simulate.
"""
import json
import sys
import traceback
from pathlib import Path

import bpy
from bpy_extras import view3d_utils
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon

OUT = ROOT / 'test-results'
OUT.mkdir(exist_ok=True)
CASES = [('CELLS', 'ROTATE'), ('CELLS', 'PAN'), ('PORTS', 'ROTATE'), ('PORTS', 'PAN')]
completed = []
current = None


def guarded(fn):
    def wrapped():
        try:
            return fn()
        except Exception:
            error = traceback.format_exc()
            print(error)
            (OUT / 'navigation-result.json').write_text(json.dumps({'ok': False, 'completed': completed, 'error': error}), encoding='utf8')
            bpy.ops.wm.quit_blender()
    return wrapped


def surface():
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    ui = next(r for r in area.regions if r.type == 'UI')
    return area, region, ui, area.spaces.active.region_3d


def send(kind, value, x, y, shift=False):
    bpy.context.window.event_simulate(type=kind, value=value, x=int(x), y=int(y), shift=shift)


@guarded
def start():
    addon.register()
    bpy.context.window.event_simulate(type='ESC', value='PRESS')
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.app.timers.register(next_case, first_interval=.5)


@guarded
def next_case():
    global current
    if not CASES:
        (OUT / 'navigation-result.json').write_text(json.dumps({'ok': True, 'blender': bpy.app.version_string, 'completed': completed}), encoding='utf8')
        print('FACTORY_NAVIGATION_TESTS_OK')
        addon.unregister()
        bpy.ops.wm.quit_blender()
        return
    current = CASES.pop(0)
    s = bpy.context.scene.factory_building
    s.bitmap = '1' * 12
    s.ports.clear()
    area, region, ui, rv3d = surface()
    area.spaces.active.show_region_ui = True
    rv3d.view_rotation = Quaternion((1, 0, 0, 0))
    rv3d.view_perspective = 'ORTHO'
    rv3d.view_distance = 9
    rv3d.view_location = (0, 0, 0)
    with bpy.context.temp_override(area=area, region=ui):
        bpy.ops.factory.edit('INVOKE_DEFAULT', mode=current[0])
    area.tag_redraw()
    bpy.app.timers.register(navigate, first_interval=.3)


@guarded
def navigate():
    area, region, ui, rv3d = surface()
    x, y = region.x + region.width / 2, region.y + region.height / 2
    send('MOUSEMOVE', 'NOTHING', x, y)
    if current[1] == 'PAN':
        send('LEFT_SHIFT', 'PRESS', x, y)
    send('MIDDLEMOUSE', 'PRESS', x, y, shift=current[1] == 'PAN')
    send('MOUSEMOVE', 'NOTHING', x + 75, y + 40, shift=current[1] == 'PAN')
    send('MIDDLEMOUSE', 'RELEASE', x + 75, y + 40, shift=current[1] == 'PAN')
    if current[1] == 'PAN':
        send('LEFT_SHIFT', 'RELEASE', x + 75, y + 40)
    bpy.app.timers.register(edit_after_navigation, first_interval=.5)


@guarded
def edit_after_navigation():
    area, region, ui, rv3d = surface()
    if current[1] == 'PAN':
        assert rv3d.view_location.length > .01, 'Native pan did not execute'
    else:
        assert rv3d.view_rotation.rotation_difference(Quaternion((1, 0, 0, 0))).angle > .01, 'Native orbit did not execute'
    assert addon._session is not None, 'Navigation exited the editing session'
    world = Vector((-1.5, -1, 0)) if current[0] == 'CELLS' else Vector((-2, -1, 0))
    point = view3d_utils.location_3d_to_region_2d(region, rv3d, world)
    x, y = point.x + region.x, point.y + region.y
    button = 'RIGHTMOUSE' if current[0] == 'CELLS' else 'LEFTMOUSE'
    send('MOUSEMOVE', 'NOTHING', x, y)
    send(button, 'PRESS', x, y)
    send(button, 'RELEASE', x, y)
    bpy.app.timers.register(verify_edit, first_interval=.4)


@guarded
def verify_edit():
    s = bpy.context.scene.factory_building
    if current[0] == 'CELLS':
        assert s.bitmap == '011111111111', f'Paint stopped after {current[1]}: {s.bitmap}'
    else:
        assert len(s.ports) == 1, f'Port editing stopped after {current[1]}'
        assert (s.ports[0].cell_x, s.ports[0].cell_z, s.ports[0].direction) == (-1, 0, 'E')
    assert addon._session is not None
    completed.append('/'.join(current))
    send('ESC', 'PRESS', 500, 400)
    bpy.app.timers.register(next_case, first_interval=.3)


bpy.app.timers.register(start, first_interval=.5)
