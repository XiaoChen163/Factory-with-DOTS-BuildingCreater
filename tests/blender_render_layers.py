"""GPU pixel regression for reference geometry and text occlusion, Blender 4.1."""
import json
import sys
import traceback
from pathlib import Path

import bpy
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Quaternion, Vector
from bpy_extras import view3d_utils

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon

OUT = ROOT / 'test-results'


def fail():
    error = traceback.format_exc()
    print(error)
    (OUT / 'render-layers-result.json').write_text(json.dumps({'ok': False, 'error': error}), encoding='utf8')
    bpy.ops.wm.quit_blender()


def start():
    try:
        addon.register()
        bpy.context.window.event_simulate(type='ESC', value='PRESS')
        area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
        rv = area.spaces.active.region_3d
        rv.view_rotation = Quaternion((1, 0, 0, 0))
        rv.view_perspective = 'ORTHO'
        rv.view_distance = 9
        rv.view_location = (0, 0, 0)
        s = bpy.context.scene.factory_building
        assert s.render_layer == 'NORMAL'
        bpy.ops.factory.add_port(edge=0, dx=-1, dy=0)
        bpy.ops.factory.add_port(edge=3, dx=1, dy=0)
        bpy.ops.factory.reverse_port()
        area.tag_redraw()
        bpy.app.timers.register(capture, first_interval=.5)
    except Exception:
        fail()


def capture():
    try:
        area = next(a for a in bpy.context.screen.areas if a.type == 'VIEW_3D')
        region = next(r for r in area.regions if r.type == 'WINDOW')
        s = bpy.context.scene.factory_building
        w, h = region.width, region.height
        captures = {}
        occluder = (.08, .10, .22, 1)
        with bpy.context.temp_override(area=area, region=region):
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
            # An opaque surface above the left half of the footprint and port.
            vertices = [(-3, -2, 1), (.1, -2, 1), (.1, 2, 1), (-3, 2, 1)]
            for layer in ('NORMAL', 'FRONT'):
                s.render_layer = layer
                buffer = gpu.types.GPUOffScreen(w, h)
                with buffer.bind(), gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                    fb = gpu.state.active_framebuffer_get()
                    fb.clear(color=(.02, .02, .02, 1), depth=1)
                    gpu.matrix.load_matrix(Matrix.Identity(4))
                    gpu.matrix.load_projection_matrix(area.spaces.active.region_3d.perspective_matrix)
                    gpu.state.blend_set('NONE')
                    gpu.state.depth_test_set('LESS_EQUAL')
                    gpu.state.depth_mask_set(True)
                    addon.draw_batch(shader, 'TRIS', [vertices[i] for i in (0, 1, 2, 0, 2, 3)], occluder)
                    addon.draw_world()
                    assert gpu.state.depth_mask_get() is True
                    assert gpu.state.depth_test_get() == 'LESS_EQUAL'
                    addon.draw_labels()
                    assert gpu.state.depth_mask_get() is True
                    assert gpu.state.depth_test_get() == 'LESS_EQUAL'
                    pixels = fb.read_color(0, 0, w, h, 4, 0, 'FLOAT')
                    pixels.dimensions = w * h * 4
                    captures[layer] = list(pixels)
                    image = bpy.data.images.new('Reference ' + layer, w, h, alpha=True)
                    image.pixels.foreach_set(pixels)
                    image.filepath_raw = str(OUT / ('render-layer-' + layer.lower() + '.png'))
                    image.file_format = 'PNG'
                    image.save()
                buffer.free()

            def point(world):
                p = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, Vector(world))
                return round(p.x), round(p.y)

            def pixel(layer, world):
                x, y = point(world)
                i = (y * w + x) * 4
                return captures[layer][i:i + 3]

            for name, world in [('grid', (-1.5, 0, 0)), ('port', (-1.96, -1, .65))]:
                normal = pixel('NORMAL', world)
                front = pixel('FRONT', world)
                assert max(abs(a - b) for a, b in zip(normal, occluder)) < .005, f'{name} not occluded: {normal}'
                assert max(abs(a - b) for a, b in zip(front, normal)) > .05, f'{name} not visible in front: {front}'
            assert pixel('NORMAL', (1.5, 0, 0))[1] > .1, 'Unoccluded grid vanished'
            x, y = point((-2, -1, .8))
            tw, th = blf.dimensions(0, 'IN')
            white = {}
            for layer, pixels in captures.items():
                white[layer] = sum(min(pixels[(j * w + i) * 4:(j * w + i) * 4 + 3]) > .75
                    for j in range(y, min(h, y + int(th) + 5))
                    for i in range(x + 6, min(w, x + 6 + int(tw) + 3)))
            assert white['FRONT'] > 2, f'Text missing in FRONT: {white}'
            assert white['NORMAL'] == 0, f'Text ignores scene depth: {white}'
        (OUT / 'render-layers-result.json').write_text(json.dumps({'ok': True, 'blender': bpy.app.version_string,
            'checks': ['default NORMAL', 'grid occlusion', 'port occlusion', 'text occlusion',
                       'FRONT overlay', 'visible geometry', 'GPU state restored']}), encoding='utf8')
        print('FACTORY_RENDER_LAYER_TESTS_OK')
        addon.unregister()
        bpy.ops.wm.quit_blender()
    except Exception:
        fail()


bpy.app.timers.register(start, first_interval=.5)
