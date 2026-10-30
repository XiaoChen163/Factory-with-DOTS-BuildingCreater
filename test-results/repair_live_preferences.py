import bpy, addon_utils, json
from pathlib import Path
assert 'factory_building_lifecycle_test' not in bpy.context.preferences.addons, 'This is not the original live preferences'
assert addon_utils.check('factory_building') == (True, True), 'Enable the fixed addon before saving preferences'
import factory_building
assert factory_building.bl_info['version'] == (0, 1, 1)
result = {'restored_live_preferences': True, 'language': bpy.context.preferences.view.language, 'addon_version': list(factory_building.bl_info['version']), 'addon_enabled': True, 'project_not_saved_or_reloaded': True}
bpy.ops.wm.save_userpref()
Path('D:/UnityProject/Factory-with-DOTS-BuildingCreater/test-results/live-preferences-restored.json').write_text(json.dumps(result), encoding='utf8')
bpy.context.area.type = 'VIEW_3D'
