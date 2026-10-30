# Factory JSON v1

由 Blender 插件导出，供 Unity 编辑器导入器生成建筑空间配置及碰撞代理。
格式版本由 `schema_version` 指定，当前为 `1`。结构校验参考
[factory-json.schema.json](factory-json.schema.json)，完整示例见
[测试建筑.Model.factory.json](../examples/测试建筑.Model.factory.json)。

## 导出入口与文件

- 右侧 `工厂建筑基础 > 导出 > 导出 .factory.json`。
- 或 `文件 > 导出 > 工厂建筑数据（.factory.json）`。
- 弹出文件选择窗口，可选择位置和文件名。`Furnace.blend` 默认对应同目录的 `Furnace.factory.json`；多重文件名如
  `Furnace.Model.blend` 对应 `Furnace.Model.factory.json`。
- 先保存 `.blend` 以确定项目名称和目录；导出使用当前 Scene 的内存数据，不会自动保存 `.blend`。
- 结束占格/端口编辑并切换到物体模式后导出，避免未提交的涂选笔画遗漏。
- 同名文件会被更新。先完成全部验证，再写临时文件并原子替换，失败不破坏上次成功导出。
- 不导出 FBX，不会修改 Unity 项目。`model_file` 只是同名 FBX 的配对文件名，不要求该 FBX 已存在。

窗口右侧提供“导出占格”“导出端口”“导出碰撞代理”，默认全部勾选，至少选择一项。
未勾选占格时，`building` 仅保留 `key` 和 `model_file`；未勾选端口或碰撞代理时，省略 `ports` 或 `colliders`。
Unity 导入约定：缺失字段表示不更新对应已有数据；勾选后导出的空数组表示更新为空。新建建筑若缺少必要数据，由导入器提示补全。
只校验本次导出内容；端口校验仍依赖当前占格的合法边界。
部分导出也会完整替换目标 JSON，不合并旧文件；覆盖已有文件由 Blender 文件窗口确认。

## 顶层结构

| 字段 | 说明 |
|---|---|
| `schema_version` | 数据协议版本，当前为 1；导入器应拒绝不支持的版本 |
| `generator` | 工具标识与插件版本，不作为建筑身份 |
| `source` | `.blend` 文件名、Scene 名、求值帧与子帧，不含绝对路径 |
| `coordinates` | 坐标、单位、原点及旋转格式约定 |
| `building` | 建筑 Key、模型配对名及占格定义 |
| `ports` | 输入口与输出口数组 |
| `colliders` | 当前 Scene 内所有有效代理，包含被隐藏的代理 |

导出不依赖物体选中状态、代理显示开关、隐藏状态或 Overlays。其他 Scene 的代理不会混入。
代理按名称排序，端口按类型和内部索引排序；不写时间戳，便于版本比较。

## 坐标和单位

**所有碰撞位置、尺寸与旋转已经转换为 Unity 局部坐标。Unity 导入时不要再次交换轴。**

建筑根节点对应 Blender 世界原点 `(0,0,0)`，也就是占格包围矩形底面中心。
代理保存相对该原点的世界求值姿态；自身及父级平移/旋转已烘入，没有父子层级需要重建。

```text
Unity position = C × Blender position

C = [1 0 0]
    [0 0 1]
    [0 1 0]

Blender (x, y, z) → Unity (x, z, y)
Unity rotation matrix = C × Blender rotation matrix × C⁻¹
```

`C⁻¹=C`。这是包含手性变化的基变换，不能仅交换 Euler 角。
`rotation` 是 Unity 坐标中的单位四元数对象 `{x,y,z,w}`，没有角度单位。
`position` 和 `size` 使用 `{x,y,z}`。

- Blender +X 对应 Unity +X；Blender +Y 对应 Unity +Z；Blender +Z 对应 Unity +Y。
- 每格固定为 1 Blender 原始单位，对应 1 个游戏格；`cell_size=1`。
- 不应用 Blender 的米/厘米显示缩放 `unit_settings.scale_length`，不额外乘 100 或 0.01。
- FBX 模型也必须在 Unity 中对齐相同的原点、朝向和单位；JSON 不代表 Blender 默认 FBX 导出预设一定满足此约定。
  模型导入流程应统一完成对应的坐标/单位规范化，不能只调整 JSON 或重复缩放碰撞体。

## 建筑与占格

```json
{
  "key": "Furnace",
  "model_file": "Furnace.fbx",
  "width": 4,
  "length": 3,
  "is_rectangle": false,
  "bitmap": "1111/1111/1100"
}
```

`key` 为 `.blend` 文件名去掉最后一个扩展名，保留大小写及中文。重命名工程会改变该 Key。
`model_file` 为同名 `.fbx` 文件名，不是 `Assets/...` 路径。

`width` 对应局部 X，`length` 对应 Unity 局部 Z。位图第一行是 Z=0，第一列是 X=0。
不裁剪空白边界、不重新居中、不填洞。至少一个占用格；全占用统一导出
`is_rectangle=true, bitmap=""`，其余用 `/` 分行，直接对应当前 Unity 建筑源表字段。

## 端口

```json
[
  {"type":"Input", "index":0, "cell_x":2, "cell_z":2, "direction_x":0, "direction_z":-1},
  {"type":"Output", "index":0, "cell_x":4, "cell_z":1, "direction_x":1, "direction_z":0,
   "output_slot":1, "number":1}
]
```

- `cell_x/cell_z` 是建筑外侧连接格，不是模型空间中的连续坐标；允许凹口和孔洞。
- 输入连接格加方向、输出连接格减方向必须落在实际占用格。
- `direction_x/direction_z` 为物流方向，沿用游戏的四向整数定义，不需要进一步转换。
- 两类 `index` 各自从 0 连续编号，最多 256 个；这是现有 Unity 源表的 byte 索引限制。
- 输出的 `output_slot` 从 1 连续编号。`number` 自动等于 `output_slot`，用于对接当前 Processor
  源表仍要求的显示编号；插件没有额外的人工出口编号。
- 输入不带 `output_slot/number`。若目标行为不是 Processor，Unity 导入器应按主项目规则忽略输出绑定列。

## 碰撞代理

共有姿态数据：

```json
{
  "name":"UnityCollider_Box",
  "type":"Box",
  "position":{"x":1,"y":3,"z":2},
  "rotation":{"x":0,"y":0,"z":0,"w":1},
  "size":{"x":2,"y":4,"z":3}
}
```

| `type` | 形状字段 | 说明 |
|---|---|---|
| `Box` | `size:{x,y,z}` | Unity 局部轴长宽高，已经交换 Blender 的 Y/Z 尺寸 |
| `Sphere` | `radius` | 正半径，无非均匀缩放 |
| `Cylinder` | `radius, height, axis:"Y"` | 总高度，未旋转局部轴为 Unity +Y |
| `Capsule` | `radius, height, axis:"Y"` | 总高度包含半球，至少为直径 |

世界姿态已经烘入位置和四元数。导入端在该姿态下构造原始形状即可，不再应用源父级变换或对象缩放。
胶囊的半球球心端点为局部 `(0, ±(height/2-radius), 0)`，再由四元数旋转并加位置。
圆柱保留为圆柱，不能直接替换成胶囊。如果物理 API 的原生圆柱沿 Z 轴，导入器需额外把原生轴对齐到这里声明的 Y 轴。

按对象类型属性识别，不靠名称前缀。所有 Scene 内代理都导出，包括隐藏代理；零代理允许，导出空数组。
缩放、镜像、剪切、非有限数值以及非法形状参数会阻止整个导出，不进行静默近似。

## Unity 导入器应承担的工作

这个文件定义空间制作数据，没有虚构行为、配方、仓储容量或加工类型等玩法配置。
Unity 端导入器需要：

1. 校验协议版本，按 `building.key` 更新对应资产，配对同名 FBX。
2. 规范化模型的原点、朝向和单位，建立/更新稳定 GUID 的 Prefab。
3. 使用已经转换的代理数据生成对应的物理 Authoring 或 Unity Physics 碰撞数据。
4. 将占格和端口字段合并到唯一的建筑 CSV 源表，保留其他玩法字段；新建筑需要填写行为等必需数据。
5. 对非 Processor 忽略输出槽绑定；对 Processor 使用导出的 `number/output_slot`。
6. 调用主项目现有静态数据库导入器，不直接把生成的 `FactoryDatabase.asset` 当作另一份编辑源。

当前插件只实现 JSON 导出，上述 Unity 导入器和 FBX 导出尚不在插件内。
