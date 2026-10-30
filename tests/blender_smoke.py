"""Run with Blender 4.1 --background --python tests/blender_smoke.py."""
import os
import sys
import tempfile
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import factory_building as addon
from factory_building import core


def run():
    addon.register()
    s = bpy.context.scene.factory_building
    assert s.width == 4 and s.length == 3 and s.bitmap == '1' * 12
    assert core.cell_at((-2, -1.5, 0), 4, 3, 1) == (0, 0)
    assert core.cell_at((2, 0, 0), 4, 3, 1) is None
    assert core.edge_center((0, 0, -1, 0), 4, 3, 1) == (-2, -1, 0)
    # Resize keeps original cell coordinates, including empty anchor and holes.
    bpy.ops.factory.apply_cells(indices='[0, 6, 10, 11]', value='0')
    before = s.bitmap
    s.width = 5
    assert s.bitmap == core.resize_bitmap(before, 4, 3, 5, 3)
    s.width = 4
    assert s.bitmap == before
    s.bitmap = '111111111100'  # 1111/1111/1100, project's concave example.
    assert (2, 1, 0, 1) in list(core.boundary_edges(s.bitmap, 4, 3))
    s.placement_kind = 'Input'
    bpy.ops.factory.add_port(edge=6, dx=0, dy=1)
    p = s.ports[0]
    assert (p.cell_x, p.cell_z, p.direction, p.index) == (2, 2, 'S', 0)
    assert not addon.errors(s)
    bpy.ops.factory.add_port(edge=6, dx=0, dy=1)
    assert len(s.ports) == 1  # Clicking the same port selects rather than duplicates.
    bpy.ops.factory.reverse_port()
    assert len(s.ports) == 1
    assert (p.kind, p.direction, p.output_slot, p.index) == ('Output', 'N', 1, 0)
    assert (p.cell_x, p.cell_z) == (2, 2) and not addon.errors(s)
    assert addon.port_label(p) == 'Slot 1'
    bpy.ops.factory.add_port(edge=7, dx=1, dy=0)
    assert s.ports[1].kind == 'Input' and s.ports[1].index == 1
    assert addon.port_label(s.ports[1]) == 'IN'
    bpy.ops.factory.reverse_port()
    assert (s.ports[1].index, s.ports[1].output_slot) == (1, 2)
    assert not addon.errors(s)
    s.ports[1].index = 0
    assert any('索引重复' in e for e in addon.errors(s))
    s.ports[1].index = 1
    s.ports[1].output_slot = 1
    assert any('产物槽重复' in e for e in addon.errors(s))
    s.ports[1].output_slot = 2
    # Direct dropdown edits must reverse flow too; counters never reuse IDs.
    s.ports[1].kind = 'Input'
    assert (s.ports[1].direction, s.ports[1].index) == ('W', 2)
    s.ports[1].kind = 'Output'
    assert (s.ports[1].direction, s.ports[1].index, s.ports[1].output_slot) == ('E', 2, 3)
    assert not addon.errors(s)
    s.bitmap = '0' * 12
    assert len(addon.errors(s)) >= 3
    s.bitmap = '111111111100'
    s.active_port = 1
    bpy.ops.factory.remove_port()
    bpy.ops.factory.add_port(edge=7, dx=1, dy=0)
    assert s.ports[1].index == 3
    assert len(s.ports) == 2 and not addon.errors(s)
    assert not hasattr(addon.FACTORY_PT_footprint, 'bl_parent_id')
    assert not hasattr(addon.FACTORY_PT_ports, 'bl_parent_id')
    # Round trip a .blend file; metadata must survive with no helper objects.
    count = len(bpy.data.objects)
    with tempfile.TemporaryDirectory(prefix='factory-building-') as directory:
        path = os.path.join(directory, 'roundtrip.blend')
        bpy.ops.wm.save_as_mainfile(filepath=path)
        s.bitmap = '0' * 12
        bpy.ops.wm.open_mainfile(filepath=path)
        s = bpy.context.scene.factory_building
        assert s.bitmap == '111111111100' and len(s.ports) == 2
        assert not addon.errors(s) and len(bpy.data.objects) == count
    addon.unregister()
    addon.register()
    addon.unregister()
    print('FACTORY_BUILDING_TESTS_OK Blender', bpy.app.version_string)


run()
