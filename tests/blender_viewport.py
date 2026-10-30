"""Foreground Blender test: UI context, click/drag tools, GPU draw, screenshot.

Run on a separate factory-startup Blender instance, never the artist's session.
"""
import json
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy
from bpy_extras import view3d_utils
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon

OUT = ROOT / 'test-results'
OUT.mkdir(exist_ok=True)


def run():
    try:
        addon.register()
        bpy.context.window.event_simulate(type='ESC', value='PRESS')
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
        space = area.spaces.active
        space.show_region_ui = True
        space.region_3d.view_rotation = Quaternion((1, 0, 0, 0))
        space.region_3d.view_perspective = 'ORTHO'
        space.region_3d.view_distance = 9
        space.region_3d.view_location = (0, 0, 0)
        space.overlay.show_floor = False
        space.overlay.show_axis_x = False
        space.overlay.show_axis_y = False
        area.tag_redraw()
        bpy.app.timers.register(interact, first_interval=1)
    except Exception:
        fail()


def fail():
    (OUT / 'viewport-result.json').write_text(json.dumps({'ok': False, 'error': traceback.format_exc()}), encoding='utf8')
    traceback.print_exc()
    bpy.ops.wm.quit_blender()


def interact():
    try:
        area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
        region = next(r for r in area.regions if r.type == 'WINDOW')
        ui = next(r for r in area.regions if r.type == 'UI')
        s = bpy.context.scene.factory_building

        def event_at(world, kind, value='PRESS'):
            p = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, Vector(world))
            return SimpleNamespace(type=kind, value=value, ctrl=False, alt=False,
                                   mouse_x=p.x + region.x, mouse_y=p.y + region.y)

        # Invoke from the sidebar, not WINDOW: a common modal context pitfall.
        with bpy.context.temp_override(area=area, region=ui):
            bpy.ops.factory.edit('INVOKE_DEFAULT', mode='CELLS')
            tool = addon._session
            assert tool is not None
            tool.modal(bpy.context, event_at((-1.5, -1, 0), 'RIGHTMOUSE'))
            tool.modal(bpy.context, event_at((1.5, -1, 0), 'MOUSEMOVE', 'NOTHING'))
            assert s.bitmap == '1' * 12  # Stroke is still a preview.
            tool.modal(bpy.context, event_at((1.5, -1, 0), 'RIGHTMOUSE', 'RELEASE'))
            assert s.bitmap == '000011111111'  # Fast drag fills skipped cells.
            tool.modal(bpy.context, event_at((-1.5, 0, 0), 'RIGHTMOUSE'))
            tool.modal(bpy.context, event_at((-1.5, 0, 0), 'ESC'))
            assert s.bitmap == '000011111111' and addon._session is None
            # Fill then restore the irregular footprint example.
            s.bitmap = '111111111100'
            bpy.ops.factory.edit('INVOKE_DEFAULT', mode='PORTS')
            tool = addon._session
            s.placement_kind = 'Input'
            tool.modal(bpy.context, event_at((0.5, .5, 0), 'LEFTMOUSE'))
            assert len(s.ports) == 1
            p = s.ports[0]
            assert (p.cell_x, p.cell_z, p.direction) == (2, 2, 'S')
            tool.modal(bpy.context, event_at((2, 0, 0), 'LEFTMOUSE'))
            assert len(s.ports) == 2 and not addon.errors(s)
            assert s.ports[1].kind == 'Input'
            tool.modal(bpy.context, event_at((2, 0, 0), 'R'))
            assert (s.ports[1].kind, s.ports[1].direction, s.ports[1].output_slot) == ('Output', 'E', 1)
            # Pick the first triangle, away from the floor boundary; switch
            # selection instead of adding a port, then reverse it with R.
            _, vertices = addon.port_vertices(s, s.ports[0])
            center = sum(vertices, Vector((0, 0, 0))) / 3
            tool.modal(bpy.context, event_at(center, 'LEFTMOUSE'))
            assert s.active_port == 0 and len(s.ports) == 2
            tool.modal(bpy.context, event_at(center, 'R'))
            assert (s.ports[0].kind, s.ports[0].direction, s.ports[0].output_slot) == ('Output', 'N', 2)
            tool.modal(bpy.context, event_at(center, 'R'))
            assert s.ports[0].kind == 'Input' and s.ports[0].direction == 'S'
            assert not addon.errors(s)
            tool.modal(bpy.context, event_at((0, 0, 0), 'RET'))
            assert addon._session is None
        # Exercise actual GPU batches and label draw in a real graphics context.
        with bpy.context.temp_override(area=area, region=region):
            addon.draw_world()
            addon.draw_labels()
        # Verify undo/redo of data mutations independently of active modal tools.
        with bpy.context.temp_override(area=area, region=region):
            bpy.ops.ed.undo_push(message='Before footprint stroke')
            bpy.ops.factory.apply_cells(indices='[0]', value='0')
            bpy.ops.ed.undo_push(message='After footprint stroke')
            bpy.ops.ed.undo()
            assert bpy.context.scene.factory_building.bitmap == '111111111100'
            bpy.ops.ed.redo()
            assert bpy.context.scene.factory_building.bitmap == '011111111100'
            bpy.context.scene.factory_building.bitmap = '111111111100'
        # Select our sidebar category if this Blender build exposes the property.
        if hasattr(ui, 'active_panel_category'):
            ui.active_panel_category = '工厂建筑基础'
        # Also dispatch real window events through Blender's modal handler.
        with bpy.context.temp_override(area=area, region=ui):
            bpy.ops.factory.edit('INVOKE_DEFAULT', mode='CELLS')
        p = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, Vector((-1.5, -1, 0)))
        for kind, value in [('MOUSEMOVE', 'NOTHING'), ('RIGHTMOUSE', 'PRESS'), ('RIGHTMOUSE', 'RELEASE'), ('ESC', 'PRESS')]:
            bpy.context.window.event_simulate(type=kind, value=value, x=int(p.x + region.x), y=int(p.y + region.y))
        area.tag_redraw()
        bpy.app.timers.register(capture, first_interval=1)
    except Exception:
        fail()


def capture():
    try:
        assert addon._session is None
        s = bpy.context.scene.factory_building
        assert s.bitmap == '011111111100', 'Real window event painting failed'
        s.bitmap = '111111111100'
        area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
        region = next(r for r in area.regions if r.type == 'WINDOW')
        ui = next(r for r in area.regions if r.type == 'UI')
        with bpy.context.temp_override(area=area, region=ui):
            bpy.ops.factory.edit('INVOKE_DEFAULT', mode='PORTS')
        _, vertices = addon.port_vertices(s, s.ports[1])
        center = sum(vertices, Vector((0, 0, 0))) / 3
        p = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, center)
        for kind, value in [('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'), ('LEFTMOUSE', 'RELEASE'), ('R', 'PRESS'), ('R', 'RELEASE'), ('ESC', 'PRESS')]:
            bpy.context.window.event_simulate(type=kind, value=value, x=int(p.x + region.x), y=int(p.y + region.y))
        bpy.app.timers.register(verify_port_events, first_interval=.5)
    except Exception:
        fail()


def verify_port_events():
    try:
        assert addon._session is None
        s = bpy.context.scene.factory_building
        assert len(s.ports) == 2 and s.active_port == 1
        assert (s.ports[1].kind, s.ports[1].direction) == ('Input', 'W'), 'Real triangle selection / R event failed'
        bpy.ops.factory.reverse_port()
        assert not addon.errors(s)
        # Screenshot on the next redraw so the restored state is visible.
        bpy.app.timers.register(save_capture, first_interval=.5)
    except Exception:
        fail()


def save_capture():
    try:
        bpy.ops.screen.screenshot(filepath=str(OUT / 'blender-4.1-viewport.png'))
        # Deterministic orthographic GPU capture, independent of desktop visibility.
        import gpu
        from mathutils import Matrix
        area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
        region = next(r for r in area.regions if r.type == 'WINDOW')
        buffer = gpu.types.GPUOffScreen(1000, 800)
        with bpy.context.temp_override(area=area, region=region):
            with buffer.bind():
                gpu.state.active_framebuffer_get().clear(color=(.055, .055, .055, 1), depth=1)
                projection = Matrix(((.3, 0, 0, 0), (0, .375, 0, 0), (0, 0, -.1, 0), (0, 0, 0, 1)))
                with gpu.matrix.push_pop():
                    gpu.matrix.load_matrix(Matrix.Identity(4))
                    gpu.matrix.load_projection_matrix(projection)
                    addon.draw_world()
                pixels = gpu.state.active_framebuffer_get().read_color(0, 0, 1000, 800, 4, 0, 'FLOAT')
                pixels.dimensions = 1000 * 800 * 4
                image = bpy.data.images.new('Factory grid verification', 1000, 800, alpha=True)
                image.pixels.foreach_set(pixels)
                image.filepath_raw = str(OUT / 'blender-4.1-grid.png')
                image.file_format = 'PNG'
                image.save()
            buffer.free()
        (OUT / 'viewport-result.json').write_text(json.dumps({'ok': True, 'blender': bpy.app.version_string,
            'checks': ['sidebar invocation', 'drag paint', 'cancel stroke', 'concave input', 'output placement', 'triangle selection', 'R reverse and numbering', 'GPU draw', 'labels', 'undo', 'redo', 'real window mouse events']}), encoding='utf8')
        print('FACTORY_VIEWPORT_TESTS_OK')
        addon.unregister()
        bpy.ops.wm.quit_blender()
    except Exception:
        fail()


bpy.app.timers.register(run, first_interval=1)
