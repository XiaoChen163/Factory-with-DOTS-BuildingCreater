"""Versioned Factory metadata with selectable sections and export destination.

Coordinates are already Unity-local: Blender (x,y,z) -> Unity (x,z,y).
This swaps handedness. Rotations use C @ R @ C, NOT an Euler-axis swap.
"""
import importlib
import json
import math
import os
from pathlib import Path
import tempfile

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ExportHelper
from mathutils import Matrix

from . import colliders, core

SCHEMA_VERSION = 1
AXIS_CHANGE = Matrix(((1, 0, 0), (0, 0, 1), (0, 1, 0)))


class ExportValidationError(ValueError):
    pass


def export_path():
    if not bpy.data.filepath:
        raise ExportValidationError('请先保存 .blend 工程，再导出同名数据')
    return Path(bpy.data.filepath).with_suffix('.factory.json')


def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise ExportValidationError('数据含有 NaN 或无穷大')
    return 0.0 if abs(value) < 1e-10 else round(value, 9)


def vector(value):
    return {axis: number(component) for axis, component in zip('xyz', value)}


def validate_transform(obj, matrix):
    if not all(math.isfinite(v) for row in matrix for v in row):
        raise ExportValidationError(f'碰撞代理“{obj.name}”的变换含有非有限数值')
    ancestor = obj
    while ancestor is not None:
        if any(not math.isfinite(v) or abs(v - 1) > 1e-4
               for v in (*ancestor.scale, *ancestor.delta_scale)):
            raise ExportValidationError(f'碰撞代理“{obj.name}”或父级“{ancestor.name}”存在缩放，请恢复为 1')
        ancestor = ancestor.parent
    rotation = matrix.to_3x3()
    columns = list(rotation.col)
    if (any(abs(column.length - 1) > 1e-4 for column in columns)
            or any(abs(columns[i].dot(columns[j])) > 1e-4 for i in range(3) for j in range(i))
            or abs(rotation.determinant() - 1) > 1e-4):
        raise ExportValidationError(f'碰撞代理“{obj.name}”含有缩放、剪切或镜像变换')


def collider_record(obj, depsgraph):
    p = obj.factory_collider
    if obj.type != 'EMPTY' or p.kind not in colliders.NAMES:
        raise ExportValidationError(f'碰撞代理“{obj.name}”的类型或标记无效')
    world = obj.evaluated_get(depsgraph).matrix_world.copy()
    validate_transform(obj, world)
    converted_rotation = (AXIS_CHANGE @ world.to_3x3() @ AXIS_CHANGE).to_quaternion()
    converted_rotation.normalize()
    if converted_rotation.w < 0:
        converted_rotation.negate()
    record = {
        'name': obj.name,
        'type': p.kind.title(),
        'position': vector(AXIS_CHANGE @ world.translation),
        'rotation': {axis: number(getattr(converted_rotation, axis)) for axis in 'xyzw'},
    }
    if p.kind == 'BOX':
        if any(not math.isfinite(v) or v <= 0 for v in p.size):
            raise ExportValidationError(f'盒体“{obj.name}”尺寸必须为正数')
        record['size'] = vector((p.size[0], p.size[2], p.size[1]))
    else:
        if not math.isfinite(p.radius) or p.radius <= 0:
            raise ExportValidationError(f'碰撞代理“{obj.name}”半径必须为正数')
        record['radius'] = number(p.radius)
        if p.kind in {'CYLINDER', 'CAPSULE'}:
            if not math.isfinite(p.height) or p.height <= 0:
                raise ExportValidationError(f'碰撞代理“{obj.name}”高度必须为正数')
            if p.kind == 'CAPSULE' and p.height < 2 * p.radius - 1e-6:
                raise ExportValidationError(f'胶囊体“{obj.name}”总高度不得小于直径')
            record['height'] = number(p.height)
            record['axis'] = 'Y'
    return record


def build_document(context, export_footprint=True, export_ports=True, export_colliders=True):
    addon = importlib.import_module(__package__)
    if addon._session is not None:
        raise ExportValidationError('请先按 Enter 或 Esc 结束占格/端口编辑，再导出')
    source = Path(bpy.data.filepath) if bpy.data.filepath else None
    if source is None:
        raise ExportValidationError('请先保存 .blend 工程，再导出同名数据')
    if not any((export_footprint, export_ports, export_colliders)):
        raise ExportValidationError('请至少选择一项导出内容')
    s = context.scene.factory_building
    if export_footprint or export_ports:
        if not (1 <= s.width <= 255 and 1 <= s.length <= 255):
            raise ExportValidationError('占格长宽必须在 1 到 255 之间')
        if len(s.bitmap) != s.width * s.length or any(c not in '01' for c in s.bitmap):
            raise ExportValidationError('占格位图必须是与长宽一致的 0/1 数据')
        if '1' not in s.bitmap:
            raise ExportValidationError('至少需要一个占用格')
    if export_ports:
        for p in s.ports:
            if p.kind not in {'Input', 'Output'} or p.direction not in core.DIRECTIONS:
                raise ExportValidationError('端口类型或方向无效')
            if not 0 <= p.index <= 255:
                raise ExportValidationError('每类端口最多支持 256 个，内部索引必须在 0 到 255 之间')
        issues = addon.errors(s)
        if issues:
            raise ExportValidationError('\n'.join(issues))
        for kind in ('Input', 'Output'):
            indices = sorted(p.index for p in s.ports if p.kind == kind)
            if indices != list(range(len(indices))):
                raise ExportValidationError(f'{kind} 内部索引必须从 0 连续排列')
        slots = sorted(p.output_slot for p in s.ports if p.kind == 'Output')
        if slots != list(range(1, len(slots) + 1)):
            raise ExportValidationError('产物槽位必须从 1 连续排列')

    ports = []
    for p in sorted(s.ports if export_ports else [], key=lambda p: (p.kind, p.index)):
        dx, dz = core.DIRECTIONS[p.direction]
        record = {'type': p.kind, 'index': p.index, 'cell_x': p.cell_x, 'cell_z': p.cell_z,
                  'direction_x': dx, 'direction_z': dz}
        if p.kind == 'Output':
            record['output_slot'] = p.output_slot
            # Unity's existing Processor CSV requires a displayed number as
            # well as a slot. It is derived, never separately artist-authored.
            record['number'] = p.output_slot
        ports.append(record)

    exported_colliders = []
    if export_colliders:
        context.view_layer.update()
        graph = context.evaluated_depsgraph_get()
        candidates = [obj for obj in context.scene.objects
                      if obj.factory_collider.kind != 'NONE' or obj.get('factory_role') == 'collider']
        exported_colliders = [collider_record(obj, graph) for obj in sorted(candidates, key=lambda obj: obj.name)]
    building = {'key': source.stem, 'model_file': source.stem + '.fbx'}
    if export_footprint:
        rectangle = all(c == '1' for c in s.bitmap)
        bitmap = '' if rectangle else '/'.join(s.bitmap[i:i + s.width] for i in range(0, len(s.bitmap), s.width))
        building.update(width=s.width, length=s.length, is_rectangle=rectangle, bitmap=bitmap)
    document = {
        'schema_version': SCHEMA_VERSION,
        'generator': {'name': 'factory_building', 'version': '.'.join(map(str, addon.bl_info['version']))},
        'source': {'blend_file': source.name, 'scene': context.scene.name,
                   'frame': context.scene.frame_current, 'subframe': number(context.scene.frame_subframe)},
        'coordinates': {'space': 'unity_local', 'origin': 'footprint_bounds_bottom_center',
                        'up_axis': 'Y', 'forward_axis': '+Z', 'cell_size': 1.0,
                        'unit': 'blender_unit', 'rotation_format': 'quaternion_xyzw',
                        'blender_to_unity': [[1, 0, 0], [0, 0, 1], [0, 1, 0]]},
        'building': building,
        'ports': ports,
        'colliders': exported_colliders,
    }
    if not export_ports:
        del document['ports']
    if not export_colliders:
        del document['colliders']
    return document


def write_document(path, document):
    """Validate/encode first, then atomically replace the previous snapshot."""
    encoded = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + '\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         prefix='.' + path.name + '.', suffix='.tmp',
                                         dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class FACTORY_OT_export(bpy.types.Operator, ExportHelper):
    bl_idname = 'factory.export_json'
    bl_label = '导出 .factory.json'
    bl_description = '选择保存位置及需要导出的占格、端口和碰撞代理'
    filename_ext = '.factory.json'
    filter_glob: StringProperty(default='*.factory.json', options={'HIDDEN'})
    export_footprint: BoolProperty(name='导出占格', default=True)
    export_ports: BoolProperty(name='导出端口', default=True)
    export_colliders: BoolProperty(name='导出碰撞代理', default=True)

    def check(self, context):
        # ExportHelper strips only the last suffix; with a compound extension
        # that would repeatedly append '.factory'. Keep this check idempotent.
        path = bpy.path.ensure_ext(self.filepath, self.filename_ext)
        changed = path != self.filepath
        self.filepath = path
        return changed

    def invoke(self, context, event):
        self.filepath = str(export_path())
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'export_footprint')
        layout.prop(self, 'export_ports')
        layout.prop(self, 'export_colliders')
        if not any((self.export_footprint, self.export_ports, self.export_colliders)):
            layout.label(text='请至少选择一项', icon='ERROR')

    @classmethod
    def poll(cls, context):
        addon = importlib.import_module(__package__)
        if not bpy.data.filepath:
            cls.poll_message_set('请先保存 .blend 工程')
            return False
        if context.mode != 'OBJECT' or addon._session is not None:
            cls.poll_message_set('请先结束编辑并切换到物体模式')
            return False
        return True

    def execute(self, context):
        try:
            document = build_document(context, self.export_footprint, self.export_ports, self.export_colliders)
            path = Path(bpy.path.abspath(self.filepath)) if self.filepath else export_path()
            path = Path(bpy.path.ensure_ext(str(path), self.filename_ext))
            write_document(path, document)
        except (ExportValidationError, OSError, ValueError) as error:
            self.report({'WARNING'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f'已导出 {path}（{len(document.get("ports", []))} 个端口，{len(document.get("colliders", []))} 个碰撞代理）')
        return {'FINISHED'}


class FACTORY_PT_export(bpy.types.Panel):
    bl_label = '导出'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = '工厂建筑基础'

    def draw(self, context):
        self.layout.operator_context = 'INVOKE_DEFAULT'
        self.layout.operator('factory.export_json', icon='EXPORT')
        if bpy.data.filepath:
            self.layout.label(text=export_path().name)
            self.layout.label(text='在弹出窗口中选择位置和导出内容')
        else:
            self.layout.label(text='请先保存 .blend 工程', icon='INFO')


def export_menu(self, context):
    self.layout.operator_context = 'INVOKE_DEFAULT'
    self.layout.operator('factory.export_json', text='工厂建筑数据（.factory.json）')


CLASSES = (FACTORY_OT_export, FACTORY_PT_export)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_export.append(export_menu)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(export_menu)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
