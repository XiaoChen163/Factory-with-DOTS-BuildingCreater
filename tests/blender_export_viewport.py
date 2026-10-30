"""Real Blender 4.1 GUI registration/menu and saved-project export flow."""
import json
from pathlib import Path
import sys
import tempfile
import traceback

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon
from factory_building import colliders, exporter

OUT = ROOT / 'test-results'
temporary = tempfile.TemporaryDirectory(prefix='factory-export-gui-')
seen_menu = []


def checked(fn):
    def call():
        try:
            fn()
        except Exception:
            error = traceback.format_exc()
            print(error)
            (OUT / 'export-viewport-result.json').write_text(json.dumps({'ok': False, 'error': error}), encoding='utf8')
            temporary.cleanup()
            bpy.ops.wm.quit_blender()
    return call


def observe(self, context):
    seen_menu.append(exporter.FACTORY_OT_export.poll(context))


def surface():
    area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
    return area, next(r for r in area.regions if r.type == 'WINDOW')


@checked
def start():
    for cls in (addon.FACTORY_PT_footprint, addon.FACTORY_PT_ports, colliders.FACTORY_PT_colliders):
        cls.bl_options = {'DEFAULT_CLOSED'}
    addon.register()
    assert not exporter.FACTORY_OT_export.poll(bpy.context)
    bpy.context.window.event_simulate(type='ESC', value='PRESS')
    bpy.ops.factory.add_port(edge=0, dx=-1, dy=0)
    bpy.ops.factory.add_collider(kind='BOX')
    bpy.context.object.factory_collider.size = (2, 3, 4)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path(temporary.name) / 'Export测试.Model.blend'))
    bpy.types.TOPBAR_MT_file_export.append(observe)
    bpy.app.timers.register(menu_test, first_interval=.5)


@checked
def menu_test():
    area, region = surface()
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.wm.call_menu(name='TOPBAR_MT_file_export')
    bpy.app.timers.register(export_once, first_interval=.4)


@checked
def export_once():
    assert any(seen_menu), 'File > Export menu was not drawn in the saved-project context'
    bpy.ops.screen.screenshot(filepath=str(OUT / 'factory-export-menu.png'))
    bpy.context.window.event_simulate(type='ESC', value='PRESS')
    bpy.app.timers.register(do_export, first_interval=.2)


@checked
def do_export():
    assert bpy.ops.factory.export_json('INVOKE_DEFAULT') == {'RUNNING_MODAL'}
    bpy.app.timers.register(file_dialog, first_interval=.8)


@checked
def file_dialog():
    window, area = next((w, a) for w in bpy.context.window_manager.windows
                        for a in w.screen.areas if a.type == 'FILE_BROWSER')
    op = area.spaces.active.active_operator
    assert op and op.bl_rna.identifier == 'FACTORY_OT_export_json', repr(op)
    assert op.export_footprint and op.export_ports and op.export_colliders
    assert area.spaces.active.params.filename == 'Export测试.Model.factory.json'
    target = Path(temporary.name) / '自选导出目录'
    target.mkdir()
    area.spaces.active.params.directory = str(target).encode('utf8')
    area.spaces.active.params.filename = 'Custom.factory.json'
    op.export_ports = False
    region = next(r for r in area.regions if r.type == 'WINDOW')
    with bpy.context.temp_override(window=window, area=area, region=region):
        bpy.ops.screen.screenshot(filepath=str(OUT / 'factory-export-dialog.png'))
        bpy.ops.file.execute()
    bpy.app.timers.register(check_export, first_interval=.5)


@checked
def check_export():
    path = Path(temporary.name) / '自选导出目录' / 'Custom.factory.json'
    first = json.loads(path.read_text(encoding='utf8'))
    assert 'ports' not in first
    assert first['building']['key'] == 'Export测试.Model'
    assert first['colliders'][0]['size'] == {'x': 2.0, 'y': 4.0, 'z': 3.0}
    area, region = surface()
    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.factory.edit('INVOKE_DEFAULT', mode='CELLS')
    assert not exporter.FACTORY_OT_export.poll(bpy.context)
    try:
        exporter.build_document(bpy.context)
    except exporter.ExportValidationError:
        pass
    else:
        raise AssertionError('Export accepted an unfinished editing session')
    bpy.context.window.event_simulate(type='ESC', value='PRESS')
    bpy.app.timers.register(overwrite, first_interval=.3)


@checked
def overwrite():
    assert addon._session is None and exporter.FACTORY_OT_export.poll(bpy.context)
    bpy.context.object.factory_collider.size = (5, 6, 7)
    assert bpy.ops.factory.export_json() == {'FINISHED'}
    data = json.loads(exporter.export_path().read_text(encoding='utf8'))
    assert data['colliders'][0]['size'] == {'x': 5.0, 'y': 7.0, 'z': 6.0}
    (OUT / 'export-viewport-result.json').write_text(json.dumps({'ok': True, 'blender': bpy.app.version_string,
        'checks': ['unsaved disabled', 'File Export menu', 'native file selector with three default checks',
                   'custom Unicode directory and filename', 'unchecked ports omitted',
                   'editing session blocked', 'overwrite latest parameters']}), encoding='utf8')
    bpy.types.TOPBAR_MT_file_export.remove(observe)
    addon.unregister()
    temporary.cleanup()
    print('FACTORY_EXPORT_VIEWPORT_TESTS_OK')
    bpy.ops.wm.quit_blender()


bpy.app.timers.register(start, first_interval=.5)
