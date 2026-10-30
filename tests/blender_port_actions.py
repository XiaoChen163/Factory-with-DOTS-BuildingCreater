"""Foreground regression for list Delete, context menus and Alt+D."""
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

OUT = ROOT / 'test-results'
menu_draws = []


def observed_menu(self, context):
    menu_draws.append('list' if addon.is_port_list(context) else 'viewport')


def checked(fn):
    def call():
        try:
            fn()
        except Exception:
            error = traceback.format_exc()
            print(error)
            (OUT / 'port-actions-result.json').write_text(json.dumps({'ok': False, 'error': error, 'menus': menu_draws}), encoding='utf8')
            bpy.ops.screen.screenshot(filepath=str(OUT / 'port-actions-failure.png'))
            bpy.ops.wm.quit_blender()
    return call


def surface():
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    return area, next(r for r in area.regions if r.type == 'WINDOW'), next(r for r in area.regions if r.type == 'UI')


def send(key, value='PRESS', *, sidebar=False, alt=False):
    area, region, ui = surface()
    if sidebar:
        x, y = ui.x + 100, ui.y + ui.height - 460
    else:
        point = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, Vector((0, 0, 0)))
        x, y = region.x + point.x, region.y + point.y
    bpy.context.window.event_simulate(type=key, value=value, alt=alt, x=int(x), y=int(y))


def add_port(edge=1):
    bpy.ops.factory.add_port(edge=edge, dx=0, dy=-1)


@checked
def start():
    addon.register()
    bpy.types.FACTORY_MT_port_context.append(observed_menu)
    bpy.context.window.event_simulate(type='ESC', value='PRESS')
    area, region, ui = surface()
    area.spaces.active.show_region_ui = True
    rv = area.spaces.active.region_3d
    rv.view_rotation = Quaternion((1, 0, 0, 0))
    rv.view_perspective = 'ORTHO'
    rv.view_distance = 9
    rv.view_location = (0, 0, 0)
    for edge in (0, 1, 2):
        add_port(edge)
        bpy.ops.factory.reverse_port()
    bpy.context.scene.factory_building.active_port = 1
    area.tag_redraw()
    bpy.app.timers.register(select_category, first_interval=.7)


@checked
def select_category():
    area, region, ui = surface()
    x, y = ui.x + ui.width - 12, ui.y + ui.height - 225
    for kind, value in [('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE')]:
        bpy.context.window.event_simulate(type=kind, value=value, x=int(x), y=int(y))
    bpy.app.timers.register(list_delete, first_interval=.5)


@checked
def list_delete():
    area, region, ui = surface()
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.ed.undo_push(message='Before list deletion')
    bpy.ops.screen.screenshot(filepath=str(OUT / 'port-list-before-delete.png'))
    send('MOUSEMOVE', 'NOTHING', sidebar=True)
    send('DEL', sidebar=True)
    send('DEL', 'RELEASE', sidebar=True)
    bpy.app.timers.register(list_menu, first_interval=.4)


@checked
def list_menu():
    s = bpy.context.scene.factory_building
    assert len(s.ports) == 2, 'Delete over the port list did not remove the selected port'
    assert [p.output_slot for p in s.ports] == [1, 2]
    area, region, ui = surface()
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.ed.undo()
        assert len(bpy.context.scene.factory_building.ports) == 3
        bpy.ops.ed.redo()
        assert [p.output_slot for p in bpy.context.scene.factory_building.ports] == [1, 2]
    send('MOUSEMOVE', 'NOTHING', sidebar=True)
    send('RIGHTMOUSE', sidebar=True)
    send('RIGHTMOUSE', 'RELEASE', sidebar=True)
    bpy.app.timers.register(sidebar_alt_delete, first_interval=.4)


@checked
def sidebar_alt_delete():
    assert 'list' in menu_draws, 'List context menu was not built'
    send('ESC', sidebar=True)
    bpy.app.timers.register(do_sidebar_delete, first_interval=.2)


@checked
def do_sidebar_delete():
    send('D', sidebar=True, alt=True)
    send('D', 'RELEASE', sidebar=True, alt=True)
    bpy.app.timers.register(viewport_alt_delete, first_interval=.4)


@checked
def viewport_alt_delete():
    assert len(bpy.context.scene.factory_building.ports) == 1, 'Alt+D in sidebar failed'
    send('MOUSEMOVE', 'NOTHING')
    send('D', alt=True)
    send('D', 'RELEASE', alt=True)
    bpy.app.timers.register(modal_delete, first_interval=.4)


@checked
def modal_delete():
    assert not bpy.context.scene.factory_building.ports, 'Alt+D in viewport failed'
    add_port()
    area, region, ui = surface()
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.factory.edit('INVOKE_DEFAULT', mode='PORTS')
    send('RIGHTMOUSE')
    send('RIGHTMOUSE', 'RELEASE')
    bpy.app.timers.register(close_viewport_menu, first_interval=.4)


@checked
def close_viewport_menu():
    assert 'viewport' in menu_draws, 'Viewport context menu was not built'
    send('ESC')
    bpy.app.timers.register(delete_in_modal, first_interval=.3)


@checked
def delete_in_modal():
    assert addon._session and addon._session.mode == 'PORTS', 'Closing popup exited editing'
    send('DEL')
    send('DEL', 'RELEASE')
    bpy.app.timers.register(delete_in_cells, first_interval=.3)


@checked
def delete_in_cells():
    assert not bpy.context.scene.factory_building.ports
    add_port()
    send('S', alt=True)
    send('S', 'RELEASE', alt=True)
    send('D', alt=True)
    send('D', 'RELEASE', alt=True)
    bpy.app.timers.register(finish, first_interval=.4)


@checked
def finish():
    assert addon._session.mode == 'CELLS' and not bpy.context.scene.factory_building.ports
    # Menu entries share the same tested delete/reverse operators as buttons.
    from types import SimpleNamespace
    entries = []
    layout = SimpleNamespace(operator_context='INVOKE_REGION_WIN',
        operator=lambda identifier, **kwargs: entries.append((identifier, kwargs['text'])))
    addon.FACTORY_MT_port_context.draw(SimpleNamespace(layout=layout), bpy.context)
    assert entries == [('factory.remove_port', '删除'), ('factory.reverse_port', '反转')]
    bpy.types.FACTORY_MT_port_context.remove(observed_menu)
    addon.unregister()
    (OUT / 'port-actions-result.json').write_text(json.dumps({'ok': True, 'blender': bpy.app.version_string,
        'checks': ['list Delete', 'list menu', 'viewport menu', 'sidebar Alt+D', 'viewport Alt+D',
                   'modal Delete', 'cells Alt+D', 'slot compaction', 'delete undo/redo']}), encoding='utf8')
    print('FACTORY_PORT_ACTION_TESTS_OK')
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(start, first_interval=.5)
