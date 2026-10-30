bl_info = {
    "name": "工厂建筑基础", "author": "Factory with DOTS",
    "version": (0, 1, 2), "blender": (4, 1, 0),
    "location": "3D View > Sidebar > 工厂建筑基础",
    "description": "建筑底面占格与物流端口编辑", "category": "3D View",
}

import json

import bpy
import blf
import gpu
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy.app.handlers import persistent

from . import core

_handles = []
_session = None
_cache = None


def redraw():
    # addon_utils enables/disables under RestrictBlend: bpy.data intentionally
    # has no scenes/screens there. Registration must not access scene data.
    for screen in getattr(bpy.data, 'screens', ()):
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def changed(self, context):
    redraw()


def resized(self, context):
    self.bitmap = core.resize_bitmap(self.bitmap, self.stored_width, self.stored_length, self.width, self.length)
    self.stored_width = self.width
    self.stored_length = self.length
    redraw()


def allocate_index(s, kind, exclude=None):
    field = 'next_input_index' if kind == 'Input' else 'next_output_index'
    value = max(getattr(s, field), max((p.index + 1 for p in s.ports
                if p.kind == kind and p != exclude), default=0))
    setattr(s, field, value + 1)
    return value


def assign_output_slot(s, p):
    p.output_slot = max(s.next_output_slot, max((q.output_slot + 1 for q in s.ports
                        if q.kind == 'Output' and q != p), default=1))
    s.next_output_slot = p.output_slot + 1
    p.number = p.output_slot  # Legacy data compatibility; no separate UI number.


def kind_changed(self, context):
    # Remember the last kind so direct property edits also reverse flow, while
    # preserving the same physical boundary and outside connection cell.
    previous = self.get('_last_kind', 'Input')
    self['_last_kind'] = self.kind
    if previous != self.kind:
        self.direction = {'E': 'W', 'W': 'E', 'N': 'S', 'S': 'N'}[self.direction]
        s = self.id_data.factory_building
        self.index = allocate_index(s, self.kind, self)
        if self.kind == 'Output':
            assign_output_slot(s, self)
    redraw()


class FactoryPort(bpy.types.PropertyGroup):
    kind: EnumProperty(name="类型", items=[('Input', '输入', ''), ('Output', '输出', '')], update=kind_changed)
    index: IntProperty(name="内部索引", min=0, options={'HIDDEN'})
    cell_x: IntProperty(name="连接格 X", update=changed)
    cell_z: IntProperty(name="连接格 Z（Blender Y）", update=changed)
    direction: EnumProperty(name="物流方向", items=[('E', '+X', ''), ('W', '-X', ''), ('N', '+Z（Blender +Y）', ''), ('S', '-Z（Blender -Y）', '')], update=changed)
    number: IntProperty(name="旧版出口编号", default=1, min=1, options={'HIDDEN'})
    output_slot: IntProperty(name="产物槽", default=1, min=1, update=changed)


class FactorySettings(bpy.types.PropertyGroup):
    visible: BoolProperty(name="显示建筑参考", default=True, update=changed)
    width: IntProperty(name="宽（X 格数）", default=4, min=1, max=128, update=resized)
    length: IntProperty(name="长（Y 格数）", default=3, min=1, max=128, update=resized)
    stored_width: IntProperty(default=4)
    stored_length: IntProperty(default=3)
    bitmap: StringProperty(default='111111111111', update=changed)
    cell_size: FloatProperty(name="每格尺寸", default=1, min=.01, max=1000, update=changed)
    opacity: FloatProperty(name="栅格透明度", default=.25, min=.05, max=.8, update=changed)
    port_height: FloatProperty(name="箭头高度（格）", default=.65, min=.05, max=10, update=changed)
    processor: BoolProperty(name="加工建筑（绑定产物槽）", default=True, update=changed)
    placement_kind: EnumProperty(name="添加类型", items=[('Input', '输入', ''), ('Output', '输出', '')])
    ports: CollectionProperty(type=FactoryPort)
    active_port: IntProperty(default=0, min=0, update=changed)
    next_input_index: IntProperty(default=0, min=0, options={'HIDDEN'})
    next_output_index: IntProperty(default=0, min=0, options={'HIDDEN'})
    next_output_slot: IntProperty(default=1, min=1, options={'HIDDEN'})


def errors(s):
    result = []
    if '1' not in s.bitmap:
        result.append('至少需要一个占用格')
    identities, geometry, slots = set(), set(), set()
    for i, p in enumerate(s.ports):
        issue = core.port_error(s.bitmap, s.width, s.length, p.cell_x, p.cell_z, core.DIRECTIONS[p.direction], p.kind)
        if issue:
            result.append(f'端口 {i + 1}：{issue}')
        identity = (p.kind, p.index)
        location = (p.kind, p.cell_x, p.cell_z, p.direction)
        if identity in identities:
            result.append(f'端口 {i + 1}：同类型内部索引重复')
        if location in geometry:
            result.append(f'端口 {i + 1}：位置与方向重复')
        identities.add(identity)
        geometry.add(location)
        if p.kind == 'Output':
            if p.output_slot in slots:
                result.append(f'端口 {i + 1}：产物槽重复')
            slots.add(p.output_slot)
    return result


def effective_bitmap(s):
    if _session and _session.scene == bpy.context.scene and _session.mode == 'CELLS':
        bits = list(s.bitmap)
        for index in _session.pending:
            if index < len(bits):
                bits[index] = _session.paint
        return ''.join(bits)
    return s.bitmap


def draw_batch(shader, mode, positions, color):
    if positions:
        shader.bind()
        shader.uniform_float('color', color)
        batch_for_shader(shader, mode, {'pos': positions}).draw(shader)


def port_vertices(s, p):
    direction = core.DIRECTIONS[p.direction]
    edge = core.port_edge(p.cell_x, p.cell_z, direction, p.kind)
    center = Vector(core.edge_center(edge, s.width, s.length, s.cell_size))
    c = center + Vector((0, 0, s.port_height * s.cell_size))
    d = Vector((*direction, 0)) * s.cell_size
    side = Vector((-direction[1], direction[0], 0)) * s.cell_size
    return center, [c + d * .3, c - d * .22 + side * .2, c - d * .22 - side * .2]


def port_label(p):
    return 'IN' if p.kind == 'Input' else f'Slot {p.output_slot}'


def grid_batches(s, bitmap):
    global _cache
    key = (s.width, s.length, s.cell_size, bitmap)
    if _cache and _cache[0] == key:
        return _cache[1]
    fills = [[], []]
    lines = []
    w, h, unit = s.width, s.length, s.cell_size
    for y in range(h):
        for x in range(w):
            a, b = (x - w / 2) * unit, (y - h / 2) * unit
            v = [(a, b, 0), (a + unit, b, 0), (a + unit, b + unit, 0), (a, b + unit, 0)]
            fills[bitmap[y * w + x] == '1'].extend([v[0], v[1], v[2], v[0], v[2], v[3]])
    for x in range(w + 1):
        a = (x - w / 2) * unit
        lines.extend([(a, -h / 2 * unit, 0), (a, h / 2 * unit, 0)])
    for y in range(h + 1):
        b = (y - h / 2) * unit
        lines.extend([(-w / 2 * unit, b, 0), (w / 2 * unit, b, 0)])
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batches = [batch_for_shader(shader, 'TRIS', {'pos': points}) if points else None for points in fills]
    batches.append(batch_for_shader(shader, 'LINES', {'pos': lines}))
    _cache = (key, (shader, batches))
    return _cache[1]


def draw_world():
    context = bpy.context
    if not context.scene or not hasattr(context.scene, 'factory_building'):
        return
    s = context.scene.factory_building
    if not s.visible or not context.space_data.overlay.show_overlays:
        return
    shader, batches = grid_batches(s, effective_bitmap(s))
    blend = gpu.state.blend_get()
    depth = gpu.state.depth_test_get()
    try:
        gpu.state.blend_set('ALPHA')
        # Reference stays readable through the model and never writes scene depth.
        gpu.state.depth_test_set('NONE')
        for batch, color in zip(batches, [(1, .36, .36, s.opacity), (.4, 1, .55, s.opacity), (.65, .8, .8, .6)]):
            if batch:
                shader.bind()
                shader.uniform_float('color', color)
                batch.draw(shader)
        for i, p in enumerate(s.ports):
            direction = core.DIRECTIONS[p.direction]
            edge = core.port_edge(p.cell_x, p.cell_z, direction, p.kind)
            center, vertices = port_vertices(s, p)
            c = center + Vector((0, 0, s.port_height * s.cell_size))
            valid = not core.port_error(s.bitmap, s.width, s.length, p.cell_x, p.cell_z, direction, p.kind)
            color = ((.2, .8, 1, .95) if p.kind == 'Input' else (1, .65, .15, .95)) if valid else (1, .1, .2, 1)
            draw_batch(shader, 'TRIS', vertices, color)
            draw_batch(shader, 'LINES', [center, c], (*color[:3], .5))
            if i == s.active_port:
                draw_batch(shader, 'LINES', [vertices[0], vertices[1], vertices[1], vertices[2], vertices[2], vertices[0]], (1, 1, 1, 1))
        if _session and _session.scene == context.scene:
            if _session.mode == 'CELLS' and _session.hover is not None:
                x, y = _session.hover
                a, b = (x - s.width / 2) * s.cell_size, (y - s.length / 2) * s.cell_size
                u = s.cell_size
                v = [(a, b, 0), (a + u, b, 0), (a + u, b + u, 0), (a, b + u, 0)]
                draw_batch(shader, 'LINE_STRIP', v + [v[0]], (1, 1, .4, 1))
            elif _session.mode == 'PORTS' and _session.hover is not None:
                edge = _session.hover
                c = Vector(core.edge_center(edge, s.width, s.length, s.cell_size))
                side = Vector((-edge[3], edge[2], 0)) * s.cell_size * .45
                draw_batch(shader, 'LINES', [c - side, c + side], (1, 1, .2, 1))
    finally:
        gpu.state.blend_set(blend)
        gpu.state.depth_test_set(depth)


def draw_labels():
    context = bpy.context
    if not context.scene or not hasattr(context.scene, 'factory_building'):
        return
    s = context.scene.factory_building
    if not s.visible or not context.space_data.overlay.show_overlays:
        return
    blf.size(0, 13)
    for i, p in enumerate(s.ports):
        edge = core.port_edge(p.cell_x, p.cell_z, core.DIRECTIONS[p.direction], p.kind)
        c = Vector(core.edge_center(edge, s.width, s.length, s.cell_size))
        c.z = (s.port_height + .15) * s.cell_size
        pos = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, c)
        if pos:
            blf.position(0, pos.x + 6, pos.y, 0)
            blf.color(0, 1, 1, 1, 1)
            blf.draw(0, port_label(p))


class FACTORY_OT_cells(bpy.types.Operator):
    bl_idname = 'factory.apply_cells'
    bl_label = '修改建筑占格'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}
    indices: StringProperty()
    value: StringProperty(default='1')

    def execute(self, context):
        s = context.scene.factory_building
        bits = list(s.bitmap)
        for i in json.loads(self.indices):
            if 0 <= i < len(bits):
                bits[i] = self.value
        s.bitmap = ''.join(bits)
        return {'FINISHED'}


class FACTORY_OT_fill(bpy.types.Operator):
    bl_idname = 'factory.fill_cells'
    bl_label = '设置全部占格'
    bl_options = {'REGISTER', 'UNDO'}
    value: BoolProperty(default=True)

    def execute(self, context):
        s = context.scene.factory_building
        s.bitmap = ('1' if self.value else '0') * (s.width * s.length)
        return {'FINISHED'}


class FACTORY_OT_port_add(bpy.types.Operator):
    bl_idname = 'factory.add_port'
    bl_label = '添加建筑端口'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}
    edge: IntProperty()  # Flattened occupied cell; normal is separate.
    dx: IntProperty()
    dy: IntProperty()

    def execute(self, context):
        s = context.scene.factory_building
        boundary = (self.edge % s.width, self.edge // s.width, self.dx, self.dy)
        # A boundary click always starts as an input. R changes its role.
        x, y, direction = core.port_from_edge(boundary, 'Input')
        if core.port_error(s.bitmap, s.width, s.length, x, y, direction, 'Input'):
            self.report({'WARNING'}, '请选择真实占格的边界')
            return {'CANCELLED'}
        direction_key = next(k for k, v in core.DIRECTIONS.items() if v == direction)
        for i, p in enumerate(s.ports):
            if core.port_edge(p.cell_x, p.cell_z, core.DIRECTIONS[p.direction], p.kind) == boundary:
                s.active_port = i
                return {'FINISHED'}
        index = allocate_index(s, 'Input')
        p = s.ports.add()
        p.kind, p.index = 'Input', index
        p['_last_kind'] = 'Input'
        p.cell_x, p.cell_z, p.direction = x, y, direction_key
        s.active_port = len(s.ports) - 1
        redraw()
        return {'FINISHED'}


class FACTORY_OT_port_reverse(bpy.types.Operator):
    bl_idname = 'factory.reverse_port'
    bl_label = '反转选中端口'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        s = context.scene.factory_building
        return bool(s.ports) and 0 <= s.active_port < len(s.ports)

    def execute(self, context):
        s = context.scene.factory_building
        p = s.ports[s.active_port]
        boundary = core.port_edge(p.cell_x, p.cell_z, core.DIRECTIONS[p.direction], p.kind)
        target_kind = 'Output' if p.kind == 'Input' else 'Input'
        if any(q != p and q.kind == target_kind and
               core.port_edge(q.cell_x, q.cell_z, core.DIRECTIONS[q.direction], q.kind) == boundary
               for q in s.ports):
            self.report({'WARNING'}, '该边界已有同类型端口')
            return {'CANCELLED'}
        p['_last_kind'] = p.kind
        p.kind = target_kind
        return {'FINISHED'}


class FACTORY_OT_port_remove(bpy.types.Operator):
    bl_idname = 'factory.remove_port'
    bl_label = '删除选中端口'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        s = context.scene.factory_building
        if s.ports:
            s.ports.remove(min(s.active_port, len(s.ports) - 1))
            s.active_port = max(0, min(s.active_port, len(s.ports) - 1))
        redraw()
        return {'FINISHED'}


class FACTORY_OT_edit(bpy.types.Operator):
    bl_idname = 'factory.edit'
    bl_label = '编辑建筑参考'
    mode: EnumProperty(items=[('CELLS', '编辑占格', ''), ('PORTS', '编辑端口', '')])

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D' and context.mode == 'OBJECT'

    def invoke(self, context, event):
        global _session
        if _session:
            self.report({'WARNING'}, '请先按 Esc 退出当前编辑工具')
            return {'CANCELLED'}
        self.area = context.area
        self.region = next(r for r in self.area.regions if r.type == 'WINDOW')
        self.rv3d = self.area.spaces.active.region_3d
        self.scene = context.scene
        self.hover = None
        self.pending = set()
        self.paint = '1'
        self.button = None
        self.navigating = False
        self.last_cell = None
        self.signature = (self.scene.factory_building.width, self.scene.factory_building.length)
        self.scene.factory_building.visible = True
        _session = self
        text = '占格：左键涂占用，右键涂空格；Enter / Esc 退出；中键导航' if self.mode == 'CELLS' else '端口：点击边界添加输入，点击三角形选中；R 反转；Enter / Esc 退出'
        self.area.header_text_set(text)
        context.window_manager.modal_handler_add(self)
        redraw()
        return {'RUNNING_MODAL'}

    def finish(self):
        global _session
        self.pending.clear()
        try:
            self.area.header_text_set(None)
        except ReferenceError:
            pass
        if _session is self:
            _session = None
        redraw()

    def cancel(self, context):
        self.finish()

    def modal(self, context, event):
        s = context.scene.factory_building
        if (_session is not self or context.scene != self.scene or not s.visible
                or context.mode != 'OBJECT' or (s.width, s.length) != self.signature):
            self.finish()
            return {'CANCELLED'}
        if event.type in {'ESC', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            self.finish()
            return {'FINISHED'}
        if event.ctrl and event.type == 'Z':
            self.pending.clear()
            self.button = None
            self.last_cell = None
            return {'PASS_THROUGH'}
        if event.type == 'MIDDLEMOUSE':
            self.navigating = event.value != 'RELEASE'
            return {'PASS_THROUGH'}
        if self.navigating:
            return {'PASS_THROUGH'}
        if self.mode == 'PORTS' and event.type == 'R' and not event.alt and not event.ctrl:
            if event.value == 'PRESS' and not getattr(event, 'is_repeat', False) and FACTORY_OT_port_reverse.poll(context):
                bpy.ops.factory.reverse_port()
            return {'RUNNING_MODAL'}
        # A release outside WINDOW still commits the current stroke.
        if event.type == self.button and event.value == 'RELEASE':
            if self.pending:
                bpy.ops.factory.apply_cells(indices=json.dumps(sorted(self.pending)), value=self.paint)
            self.pending.clear()
            self.button = None
            self.last_cell = None
            redraw()
            return {'RUNNING_MODAL'}
        if event.alt:
            return {'PASS_THROUGH'}
        if event.type not in {'MOUSEMOVE', 'LEFTMOUSE', 'RIGHTMOUSE'}:
            return {'PASS_THROUGH'}
        mouse = (event.mouse_x - self.region.x, event.mouse_y - self.region.y)
        if not (0 <= mouse[0] < self.region.width and 0 <= mouse[1] < self.region.height):
            self.last_cell = None
            return {'PASS_THROUGH'}
        if self.mode == 'CELLS':
            origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, mouse)
            direction = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, mouse)
            self.hover = None
            if abs(direction.z) > 1e-7:
                t = -origin.z / direction.z
                if t >= 0:
                    self.hover = core.cell_at(origin + t * direction, s.width, s.length, s.cell_size)
            if event.type in {'LEFTMOUSE', 'RIGHTMOUSE'} and event.value == 'PRESS':
                self.button = event.type
                self.paint = '1' if event.type == 'LEFTMOUSE' else '0'
                self.last_cell = None
            if self.button and self.hover is not None:
                if self.last_cell is not None:
                    ax, ay = self.last_cell
                    bx, by = self.hover
                    steps = max(abs(bx - ax), abs(by - ay), 1)
                    for i in range(steps + 1):
                        x = round(ax + (bx - ax) * i / steps)
                        y = round(ay + (by - ay) * i / steps)
                        self.pending.add(y * s.width + x)
                self.pending.add(self.hover[1] * s.width + self.hover[0])
            self.last_cell = self.hover
        else:
            port = self.pick_port(mouse, s)
            self.hover = None if port is not None else self.pick_edge(context, mouse, s)
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                if port is not None:
                    s.active_port = port
                elif self.hover is not None:
                    x, y, dx, dy = self.hover
                    bpy.ops.factory.add_port(edge=y * s.width + x, dx=dx, dy=dy)
        redraw()
        return {'RUNNING_MODAL'}

    def pick_port(self, mouse, s):
        point = Vector(mouse)
        hits = []
        for i, p in enumerate(s.ports):
            _, vertices = port_vertices(s, p)
            screen = [view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, v) for v in vertices]
            if any(v is None for v in screen):
                continue
            a, b, c = screen
            cross = lambda u, v: u.x * v.y - u.y * v.x
            signs = [cross(b - a, point - a), cross(c - b, point - b), cross(a - c, point - c)]
            inside = abs(cross(b - a, c - a)) > 1e-5 and (min(signs) >= 0 or max(signs) <= 0)
            # A small pixel tolerance also handles nearly edge-on triangles.
            distance = min((point - (u + max(0, min(1, (point - u).dot(v - u) /
                max((v - u).length_squared, 1e-8))) * (v - u))).length
                for u, v in ((a, b), (b, c), (c, a)))
            if inside or distance <= 6:
                center = sum(screen, Vector((0, 0))) / 3
                hits.append(((point - center).length, i))
        return min(hits)[1] if hits else None

    def pick_edge(self, context, mouse, s):
        best, distance = None, 24 * context.preferences.system.ui_scale
        point = Vector(mouse)
        for edge in core.boundary_edges(s.bitmap, s.width, s.length):
            c = Vector(core.edge_center(edge, s.width, s.length, s.cell_size))
            side = Vector((-edge[3], edge[2], 0)) * s.cell_size * .5
            a = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, c - side)
            b = view3d_utils.location_3d_to_region_2d(self.region, self.rv3d, c + side)
            if a is None or b is None:
                continue
            segment = b - a
            t = max(0, min(1, (point - a).dot(segment) / max(segment.length_squared, 1e-8)))
            d = (point - (a + t * segment)).length
            if d < distance:
                best, distance = edge, d
        return best


class FACTORY_UL_ports(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        label = '输入' if item.kind == 'Input' else '输出'
        slot = f' · 产物槽 {item.output_slot}' if item.kind == 'Output' else ''
        layout.label(text=f'{label}{slot}  ({item.cell_x}, {item.cell_z})', icon='IMPORT' if item.kind == 'Input' else 'EXPORT')


class FACTORY_PT_footprint(bpy.types.Panel):
    bl_label = '大小和占用'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '工厂建筑基础'

    def draw(self, context):
        s = context.scene.factory_building
        col = self.layout.column()
        col.prop(s, 'visible')
        col.prop(s, 'width')
        col.prop(s, 'length')
        col.prop(s, 'cell_size')
        col.prop(s, 'opacity')
        col.operator('factory.edit', text='在视口中编辑占格', icon='BRUSH_DATA').mode = 'CELLS'
        row = col.row(align=True)
        row.operator('factory.fill_cells', text='全部占用').value = True
        row.operator('factory.fill_cells', text='全部清空').value = False
        col.label(text=f'已占用 {s.bitmap.count("1")} / {s.width * s.length} 格')
        col.label(text='原点为底面中心，栅格位于 Z=0')
        col.label(text='左键占用 / 右键清空 / Esc 退出')
        if '1' not in s.bitmap:
            col.label(text='至少需要一个占用格', icon='ERROR')


class FACTORY_PT_ports(bpy.types.Panel):
    bl_label = '端口位置'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '工厂建筑基础'

    def draw(self, context):
        s = context.scene.factory_building
        col = self.layout.column()
        col.prop(s, 'port_height')
        col.operator('factory.edit', text='在视口边界添加 / 选择端口', icon='EMPTY_ARROWS').mode = 'PORTS'
        col.template_list('FACTORY_UL_ports', '', s, 'ports', s, 'active_port', rows=3)
        if s.ports:
            p = s.ports[min(s.active_port, len(s.ports) - 1)]
            box = col.box()
            for field in ('kind', 'cell_x', 'cell_z', 'direction'):
                box.prop(p, field)
            if p.kind == 'Output':
                box.prop(p, 'output_slot')
            box.operator('factory.reverse_port', text='反转输入 / 输出（R）', icon='ARROW_LEFTRIGHT')
            box.operator('factory.remove_port', icon='TRASH')
        col.label(text='蓝色：输入；橙色：输出；红色：无效')
        col.label(text='点边界添加输入，点三角形选中，R 反转')
        issues = errors(s)
        for issue in issues[:8]:
            col.label(text=issue, icon='ERROR')
        if len(issues) > 8:
            col.label(text=f'另有 {len(issues) - 8} 项错误')


CLASSES = (FactoryPort, FactorySettings, FACTORY_OT_cells, FACTORY_OT_fill,
           FACTORY_OT_port_add, FACTORY_OT_port_reverse, FACTORY_OT_port_remove, FACTORY_OT_edit,
           FACTORY_UL_ports, FACTORY_PT_footprint, FACTORY_PT_ports)


@persistent
def before_load(_):
    if _session:
        _session.finish()


@persistent
def after_load(_):
    global _cache
    _cache = None
    initialize_ports()
    redraw()


def initialize_ports():
    """Migrate old files/enabled sessions without touching data in register()."""
    for scene in bpy.data.scenes:
        s = scene.factory_building
        for p in s.ports:
            p['_last_kind'] = p.kind
        s.next_input_index = max(s.next_input_index, max((p.index + 1 for p in s.ports if p.kind == 'Input'), default=0))
        s.next_output_index = max(s.next_output_index, max((p.index + 1 for p in s.ports if p.kind == 'Output'), default=0))
        s.next_output_slot = max(s.next_output_slot, max((p.output_slot + 1 for p in s.ports if p.kind == 'Output'), default=1))
    redraw()


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.factory_building = PointerProperty(type=FactorySettings)
    bpy.app.handlers.load_pre.append(before_load)
    bpy.app.handlers.load_post.append(after_load)
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(draw_world, (), 'WINDOW', 'POST_VIEW'))
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(draw_labels, (), 'WINDOW', 'POST_PIXEL'))
    bpy.app.timers.register(initialize_ports)


def unregister():
    global _cache
    if _session:
        _session.finish()
    if bpy.app.timers.is_registered(initialize_ports):
        bpy.app.timers.unregister(initialize_ports)
    for handle in _handles:
        bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
    _handles.clear()
    _cache = None
    bpy.app.handlers.load_pre.remove(before_load)
    bpy.app.handlers.load_post.remove(after_load)
    del bpy.types.Scene.factory_building
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    redraw()
