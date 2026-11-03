"""Empty-backed collision proxies: no mesh datablock, no editable vertices."""
from functools import lru_cache

import bpy
import bmesh
import gpu
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, PointerProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from . import collider_geometry

KINDS = [('BOX', '盒体', ''), ('SPHERE', '球体', ''), ('CYLINDER', '圆柱体', ''), ('CAPSULE', '胶囊体', '')]
NAMES = {kind: name for kind, name, _ in KINDS}
_handles = []
_keymaps = []


def redraw():
    for screen in getattr(bpy.data, 'screens', ()):
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def parameter_changed(self, context):
    if self.kind == 'CAPSULE' and self.height < 2 * self.radius:
        self.height = 2 * self.radius
    redraw()


def display_changed(self, context):
    redraw()


class FactoryCollider(bpy.types.PropertyGroup):
    kind: EnumProperty(items=[('NONE', '非代理', '')] + KINDS, default='NONE', options={'HIDDEN'})
    size: FloatVectorProperty(name='长 / 宽 / 高', description='局部 X / Y / Z 尺寸',
        size=3, default=(1, 1, 1), min=.001, soft_max=20, subtype='XYZ', update=parameter_changed)
    radius: FloatProperty(name='半径', default=.5, min=.001, soft_max=10, update=parameter_changed)
    height: FloatProperty(name='总高度', default=2, min=.002, soft_max=20, update=parameter_changed)


def is_proxy(obj):
    return obj is not None and obj.type == 'EMPTY' and obj.factory_collider.kind != 'NONE'


def rigid_matrix(obj):
    position, rotation, _ = obj.matrix_world.decompose()
    return Matrix.Translation(position) @ rotation.to_matrix().to_4x4()


def scale_error(obj):
    # Include parent/delta/constraint scaling: dimensions must come from params.
    return any(abs(v - 1) > 1e-4 for v in obj.matrix_world.to_scale())


@lru_cache(maxsize=128)
def batches(kind, size, radius, height):
    vertices, faces, edges = collider_geometry.geometry(kind, size, radius, height)
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    return (shader, batch_for_shader(shader, 'TRIS', {'pos': vertices}, indices=faces),
            batch_for_shader(shader, 'LINES', {'pos': vertices}, indices=edges))


def draw_proxies():
    context = bpy.context
    if (not context.scene or not context.scene.factory_collider_display
            or not context.space_data.overlay.show_overlays):
        return
    blend, depth, mask = gpu.state.blend_get(), gpu.state.depth_test_get(), gpu.state.depth_mask_get()
    try:
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_mask_set(False)
        gpu.state.depth_test_set('LESS_EQUAL' if context.scene.factory_building.render_layer == 'NORMAL' else 'NONE')
        for obj in context.visible_objects:
            if not is_proxy(obj):
                continue
            p = obj.factory_collider
            shader, fill, wire = batches(p.kind, tuple(p.size), p.radius, p.height)
            active = obj == context.view_layer.objects.active
            selected = obj.select_get()
            color = (1, .15, .1) if scale_error(obj) else ((1, .8, .15) if active else ((1, .45, .1) if selected else (.2, .85, 1)))
            with gpu.matrix.push_pop():
                gpu.matrix.multiply_matrix(rigid_matrix(obj))
                shader.bind()
                shader.uniform_float('color', (*color, .10 if selected else .035))
                fill.draw(shader)
                shader.uniform_float('color', (*color, 1 if selected else .8))
                wire.draw(shader)
    finally:
        gpu.state.blend_set(blend)
        gpu.state.depth_test_set(depth)
        gpu.state.depth_mask_set(mask)


def pick_proxy(context, mouse):
    if not context.scene.factory_collider_display or not context.space_data.overlay.show_overlays:
        return None
    origin = view3d_utils.region_2d_to_origin_3d(context.region, context.region_data, mouse)
    direction = view3d_utils.region_2d_to_vector_3d(context.region, context.region_data, mouse)
    best, distance = None, float('inf')
    for obj in context.visible_objects:
        if not is_proxy(obj) or obj.hide_select:
            continue
        inv = rigid_matrix(obj).inverted()
        p = obj.factory_collider
        hit = collider_geometry.ray_hit(p.kind, inv @ origin, inv.to_3x3() @ direction,
                                        tuple(p.size), p.radius, p.height)
        if hit is not None and hit < distance:
            best, distance = obj, hit
    if best and context.scene.factory_building.render_layer == 'NORMAL':
        # Respect model occlusion when normal drawing is selected. Empty proxies
        # have no mesh, so scene.ray_cast only tests the actual model geometry.
        hit, point, *_ = context.scene.ray_cast(context.evaluated_depsgraph_get(), origin, direction,
                                              distance=max(0, distance - 1e-4))
        if hit and (point - origin).length < distance - 1e-4:
            return None
    return best


def create_proxy(context, kind, *, location=None, rotation=None, parameters=None, source_name=''):
    scene = context.scene
    collection = next((c for c in scene.collection.children if c.get('factory_collider_collection')), None)
    if collection is None:
        collection = bpy.data.collections.new('工厂碰撞代理')
        collection['factory_collider_collection'] = True
        scene.collection.children.link(collection)
    name = 'UnityCollider_' + kind.title() + ('_' + source_name if source_name else '')
    obj = bpy.data.objects.new(name, None)
    collection.objects.link(obj)
    obj.factory_collider.kind = kind
    obj['factory_role'] = 'collider'
    obj.empty_display_type = 'PLAIN_AXES'
    obj.empty_display_size = .025
    obj.hide_render = True
    obj.lock_scale = (True, True, True)
    obj.location = scene.cursor.location if location is None else location
    if rotation is not None:
        obj.rotation_euler = rotation.to_euler()
    if kind == 'CYLINDER':
        obj.factory_collider.height = 1
    for key, value in (parameters or {}).items():
        setattr(obj.factory_collider, key, value)
    return obj


def select_generated(context, generated):
    for selected in context.selected_objects:
        selected.select_set(False)
    for obj in generated:
        obj.select_set(True)
    context.view_layer.objects.active = generated[-1]
    context.scene.factory_collider_display = True
    redraw()


class FACTORY_OT_collider_add(bpy.types.Operator):
    bl_idname = 'factory.add_collider'
    bl_label = '添加工厂碰撞代理'
    bl_options = {'REGISTER', 'UNDO'}
    kind: EnumProperty(name='形状', items=KINDS, default='BOX')

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        select_generated(context, [create_proxy(context, self.kind)])
        return {'FINISHED'}


FIT_TYPES = {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}


def fit_sources(context):
    selected = list(context.selected_objects)
    if not selected or any(obj.type not in FIT_TYPES or is_proxy(obj) for obj in selected):
        return []
    return selected


def evaluated_points(obj, depsgraph, frame):
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        if mesh is None or not mesh.vertices:
            raise ValueError(f'物体“{obj.name}”没有可拟合的几何顶点')
        transform = frame.inverted() @ evaluated.matrix_world
        return [transform @ v.co for v in mesh.vertices]
    finally:
        evaluated.to_mesh_clear()


class FACTORY_OT_collider_fit(bpy.types.Operator):
    bl_idname = 'factory.fit_collider'
    bl_label = '生成外接几何碰撞代理'
    bl_options = {'REGISTER', 'UNDO'}
    kind: EnumProperty(name='形状', items=KINDS, default='BOX')
    scope: EnumProperty(name='范围', items=[('EACH', '每个', ''), ('ALL', '整体', '')], default='EACH')

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(fit_sources(context))

    def execute(self, context):
        sources = fit_sources(context)
        if not sources:
            return {'CANCELLED'}
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        active = context.active_object if context.active_object in sources else sources[0]
        groups = [[obj] for obj in sources] if self.scope == 'EACH' else [sources]
        specifications = []
        try:
            # Fit all sources before modifying the scene: invalid/empty geometry
            # cannot leave a partially generated batch behind.
            for group in groups:
                reference = group[0] if self.scope == 'EACH' else active
                frame = rigid_matrix(reference.evaluated_get(depsgraph))
                points = [p for obj in group for p in evaluated_points(obj, depsgraph, frame)]
                center, parameters = collider_geometry.fit_points(self.kind, points)
                specifications.append((frame @ Vector(center), frame.to_quaternion(), parameters,
                                       reference.name if len(group) == 1 else 'Group'))
        except (ValueError, RuntimeError) as error:
            self.report({'WARNING'}, str(error))
            return {'CANCELLED'}
        generated = [create_proxy(context, self.kind, location=location, rotation=rotation,
                                  parameters=parameters, source_name=name)
                     for location, rotation, parameters, name in specifications]
        select_generated(context, generated)
        return {'FINISHED'}


FIT_NAMES = {'BOX': '立方体', 'SPHERE': '球', 'CYLINDER': '圆柱体', 'CAPSULE': '胶囊体'}


class FACTORY_OT_collider_fit_selection(bpy.types.Operator):
    bl_idname = 'factory.fit_selection_collider'
    bl_label = '为选中几何生成外接碰撞代理'
    bl_description = '使用选中顶点、边或面的编辑网格生成独立代理，保留编辑模式和当前选择；不包含修改器效果'
    bl_options = {'REGISTER', 'UNDO'}
    kind: EnumProperty(name='形状', items=KINDS, default='BOX')

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and context.edit_object is not None

    def execute(self, context):
        reference = context.edit_object
        context.view_layer.update()
        frame = rigid_matrix(reference)
        points = []
        # BMesh is the live edit cage. Selected edges/faces also select their
        # vertices; hidden geometry must never contribute to this selection.
        for obj in context.objects_in_mode:
            if obj.type != 'MESH':
                continue
            mesh = bmesh.from_edit_mesh(obj.data)
            transform = frame.inverted() @ obj.matrix_world
            points.extend(transform @ v.co for v in mesh.verts if v.select and not v.hide)
        if not points:
            self.report({'WARNING'}, '请先选择顶点、边或面')
            return {'CANCELLED'}
        try:
            center, parameters = collider_geometry.fit_points(self.kind, points)
        except ValueError as error:
            self.report({'WARNING'}, str(error))
            return {'CANCELLED'}
        # Empty creation needs a global undo snapshot; an edit-mesh-only undo
        # step would preserve the mesh but leave the new proxy behind.
        bpy.ops.object.mode_set(mode='OBJECT')
        create_proxy(context, self.kind, location=frame @ Vector(center),
                     rotation=frame.to_quaternion(), parameters=parameters,
                     source_name=reference.name + '_Selection')
        bpy.ops.ed.undo_push(message='添加选区碰撞代理')
        bpy.ops.object.mode_set(mode='EDIT')
        # Do not select the Empty or change modes: the modeler can immediately
        # select the next part and build another independent proxy.
        context.scene.factory_collider_display = True
        redraw()
        return {'FINISHED'}


class FACTORY_MT_collider_fit_selection(bpy.types.Menu):
    bl_label = '生成外接几何碰撞代理（选中部分）'

    def draw(self, context):
        for kind, _, _ in KINDS:
            self.layout.operator('factory.fit_selection_collider', text=FIT_NAMES[kind]).kind = kind


def edit_context_menu(self, context):
    if context.mode == 'EDIT_MESH':
        self.layout.separator()
        self.layout.menu('FACTORY_MT_collider_fit_selection')


def draw_fit_shapes(layout, scope):
    for kind, _, _ in KINDS:
        op = layout.operator('factory.fit_collider', text=FIT_NAMES[kind])
        op.kind, op.scope = kind, scope


class FACTORY_MT_collider_fit_each(bpy.types.Menu):
    bl_label = '生成外接几何碰撞代理'

    def draw(self, context):
        draw_fit_shapes(self.layout, 'EACH')


class FACTORY_MT_collider_fit_all(bpy.types.Menu):
    bl_label = '生成外接几何碰撞代理（整体）'

    def draw(self, context):
        draw_fit_shapes(self.layout, 'ALL')


def object_context_menu(self, context):
    if context.mode != 'OBJECT':
        return
    sources = fit_sources(context)
    if not sources:
        return
    self.layout.separator()
    if len(sources) == 1:
        self.layout.menu('FACTORY_MT_collider_fit_each', text='生成外接几何碰撞代理')
    else:
        self.layout.menu('FACTORY_MT_collider_fit_each', text='生成外接几何碰撞代理（每个）')
        self.layout.menu('FACTORY_MT_collider_fit_all', text='生成外接几何碰撞代理（整体）')


class FACTORY_OT_collider_select(bpy.types.Operator):
    bl_idname = 'factory.select_collider'
    bl_label = '选择碰撞代理'
    bl_options = {'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return (context.mode == 'OBJECT' and context.area is not None
                and context.area.type == 'VIEW_3D' and context.region.type == 'WINDOW')

    def invoke(self, context, event):
        if event.alt or event.ctrl or event.oskey:
            return {'PASS_THROUGH'}
        obj = pick_proxy(context, (event.mouse_region_x, event.mouse_region_y))
        if obj is None:
            return {'PASS_THROUGH'}
        if not event.shift:
            for selected in context.selected_objects:
                selected.select_set(False)
            obj.select_set(True)
        else:
            obj.select_set(not obj.select_get())
        if obj.select_get():
            context.view_layer.objects.active = obj
        redraw()
        return {'FINISHED'}


class FACTORY_MT_colliders(bpy.types.Menu):
    bl_label = '工厂碰撞代理'

    def draw(self, context):
        for kind, name, _ in KINDS:
            self.layout.operator('factory.add_collider', text=name).kind = kind


def add_menu(self, context):
    if context.mode == 'OBJECT':
        self.layout.separator()
        self.layout.menu('FACTORY_MT_colliders', icon='CUBE')


class FACTORY_PT_colliders(bpy.types.Panel):
    bl_label = '碰撞代理'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '工厂建筑基础'

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, 'factory_collider_display')
        if context.mode == 'EDIT_MESH':
            layout.menu('FACTORY_MT_collider_fit_selection', icon='CUBE')
            layout.label(text='选中部分拟合；保持编辑模式')
            return
        row = layout.row(align=True)
        for kind, name, _ in KINDS:
            row.operator('factory.add_collider', text=name).kind = kind
        obj = context.active_object
        if not is_proxy(obj):
            layout.label(text='选择代理以编辑形状参数')
            return
        p = obj.factory_collider
        box = layout.box()
        box.label(text=NAMES[p.kind] + ' · ' + obj.name, icon='EMPTY_DATA')
        if p.kind == 'BOX':
            box.prop(p, 'size')
        else:
            box.prop(p, 'radius')
            if p.kind in {'CYLINDER', 'CAPSULE'}:
                box.prop(p, 'height')
        box.prop(obj, 'location')
        box.prop(obj, 'rotation_euler')
        if p.kind == 'CAPSULE':
            box.label(text='总高度包含两端半球，至少为直径')
        if scale_error(obj):
            box.label(text='存在对象或父级缩放，请恢复为 1', icon='ERROR')
            box.label(text='代理外形仅使用位置、旋转和形状参数')
        layout.label(text='G 移动 / R 旋转；尺寸由参数控制')
        layout.label(text='Shift+D 复制 / Delete 删除')
        layout.label(text='代理遵循建筑参考的渲染层级')


CLASSES = (FactoryCollider, FACTORY_OT_collider_add, FACTORY_OT_collider_select,
           FACTORY_OT_collider_fit, FACTORY_MT_collider_fit_each, FACTORY_MT_collider_fit_all,
           FACTORY_OT_collider_fit_selection, FACTORY_MT_collider_fit_selection,
           FACTORY_MT_colliders, FACTORY_PT_colliders)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.factory_collider = PointerProperty(type=FactoryCollider)
    bpy.types.Scene.factory_collider_display = BoolProperty(name='显示碰撞代理', default=True, update=display_changed)
    bpy.types.VIEW3D_MT_add.append(add_menu)
    bpy.types.VIEW3D_MT_object_context_menu.append(object_context_menu)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(edit_context_menu)
    _handles.append(bpy.types.SpaceView3D.draw_handler_add(draw_proxies, (), 'WINDOW', 'POST_VIEW'))
    config = bpy.context.window_manager.keyconfigs.addon
    if config is not None:
        keymap = config.keymaps.new(name='Object Mode', space_type='EMPTY')
        item = keymap.keymap_items.new('factory.select_collider', type='LEFTMOUSE', value='PRESS', any=True, head=True)
        _keymaps.append((keymap, item))


def unregister():
    for keymap, item in _keymaps:
        keymap.keymap_items.remove(item)
    _keymaps.clear()
    for handle in _handles:
        bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
    _handles.clear()
    bpy.types.VIEW3D_MT_add.remove(add_menu)
    bpy.types.VIEW3D_MT_object_context_menu.remove(object_context_menu)
    bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(edit_context_menu)
    batches.cache_clear()
    collider_geometry.geometry.cache_clear()
    del bpy.types.Object.factory_collider
    del bpy.types.Scene.factory_collider_display
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
