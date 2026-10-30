"""Test real ZIP installation and two Blender processes with isolated preferences.

Run using Python, passing the Blender executable and packaged ZIP paths.
Never reads or writes the artist's Blender configuration.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def run():
    blender, archive = map(lambda p: str(Path(p).resolve()), sys.argv[1:3])
    with tempfile.TemporaryDirectory(prefix='factory-addon-lifecycle-', dir=Path(blender).parent.parent) as directory:
        root = Path(directory)
        # A unique module name prevents the artist's system-installed copy from
        # shadowing the ZIP under test. Contents are otherwise byte-for-byte.
        isolated_archive = root / 'factory_building_lifecycle_test.zip'
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(isolated_archive, 'w') as target:
            for entry in source.infolist():
                target.writestr(entry.filename.replace('factory_building/', 'factory_building_lifecycle_test/', 1), source.read(entry))
        archive = str(isolated_archive)
        env = dict(os.environ, BLENDER_USER_CONFIG=str(root / 'config'),
                   BLENDER_USER_SCRIPTS=str(root / 'scripts'),
                   BLENDER_USER_RESOURCES=str(root / 'user'))
        # Portable Blender prioritizes <exe>/4.1/config over environment paths.
        # Hard-link runtime files and junction read-only resource directories,
        # giving this test its own portable config directory.
        runtime = root / 'runtime'
        runtime.mkdir()
        source_runtime = Path(blender).parent
        for source_file in source_runtime.iterdir():
            if source_file.is_file():
                os.link(source_file, runtime / source_file.name)
            elif source_file.is_dir() and source_file.name != '4.1':
                (runtime / source_file.name).mkdir()
                for library in source_file.rglob('*'):
                    destination = runtime / library.relative_to(source_runtime)
                    if library.is_dir():
                        destination.mkdir()
                    elif library.is_file():
                        os.link(library, destination)
        version = runtime / '4.1'
        version.mkdir()
        (version / 'config').mkdir()
        for source_directory in (source_runtime / '4.1').iterdir():
            if source_directory.is_dir() and source_directory.name != 'config':
                result = subprocess.run(['cmd', '/c', 'mklink', '/J',
                    str(version / source_directory.name), str(source_directory)], capture_output=True)
                if result.returncode:
                    raise RuntimeError('Could not isolate Blender resources')
        blender = str(runtime / Path(blender).name)
        blend = str(root / 'building.blend')
        first = f'''
import bpy, addon_utils
from pathlib import Path
assert Path(bpy.utils.user_resource('CONFIG')).resolve().is_relative_to(Path({directory!r}).resolve()), 'Refusing to write non-test preferences'
bpy.ops.preferences.addon_install(filepath={archive!r})
failures = []
addon_utils.enable('factory_building', default_set=True, handle_error=lambda *args: failures.append(True))
assert not failures, 'Real addon enable failed under RestrictBlend'
assert addon_utils.check('factory_building') == (True, True)
s = bpy.context.scene.factory_building
s.width = 5
s.length = 4
s.bitmap = '11111001111111111111'
s.opacity = .4
s.placement_kind = 'Input'
bpy.ops.factory.add_port(edge=0, dx=-1, dy=0)
assert len(s.ports) == 1
for kind in ('BOX', 'SPHERE', 'CYLINDER', 'CAPSULE'):
    bpy.ops.factory.add_collider(kind=kind)
bpy.context.object.factory_collider.radius = .75
bpy.context.object.factory_collider.height = 3
bpy.ops.wm.save_as_mainfile(filepath={blend!r})
assert bpy.ops.factory.export_json() == {{'FINISHED'}}
bpy.ops.wm.save_userpref()
print('LIFECYCLE_INSTALL_ENABLE_SAVE_OK')
'''
        second = f'''
import bpy, addon_utils
from pathlib import Path
assert Path(bpy.utils.user_resource('CONFIG')).resolve().is_relative_to(Path({directory!r}).resolve()), 'Non-isolated configuration'
assert addon_utils.check('factory_building') == (True, True), 'Addon did not auto-enable at startup'
bpy.ops.wm.open_mainfile(filepath={blend!r})
import factory_building as addon
import json
exported = json.loads(Path({blend!r}).with_suffix('.factory.json').read_text(encoding='utf8'))
assert exported['schema_version'] == 1 and len(exported['colliders']) == 4
s = bpy.context.scene.factory_building
assert (s.width, s.length, s.bitmap) == (5, 4, '11111001111111111111')
assert s.visible and abs(s.opacity - .4) < .0001
assert len(s.ports) == 1 and s.ports[0].cell_x == -1
assert len(addon._handles) == 2
assert addon.before_load in bpy.app.handlers.load_pre
assert len(addon.colliders._handles) == 1
proxies = [o for o in bpy.context.scene.objects if addon.colliders.is_proxy(o)]
assert len(proxies) == 4
capsule = next(o for o in proxies if o.factory_collider.kind == 'CAPSULE')
assert capsule.factory_collider.radius == .75 and capsule.factory_collider.height == 3
for i in range(2):
    addon_utils.disable('factory_building', default_set=True)
    assert not addon._handles
    assert not addon.colliders._handles
    failures = []
    addon_utils.enable('factory_building', default_set=True, handle_error=lambda *args: failures.append(True))
    assert not failures and addon_utils.check('factory_building') == (True, True)
    assert len(addon._handles) == 2
    assert len(addon.colliders._handles) == 1
    assert bpy.context.scene.factory_building.bitmap == '11111001111111111111'
print('LIFECYCLE_RESTART_REOPEN_TOGGLE_OK')
'''
        for phase, script in [('install', first), ('restart', second)]:
            script = script.replace("'factory_building'", "'factory_building_lifecycle_test'").replace('import factory_building as addon', 'import factory_building_lifecycle_test as addon')
            command = [blender, '--background']
            if phase == 'install':
                command.append('--factory-startup')
            command.extend(['--python-exit-code', '1', '--python-expr', script])
            result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf8', errors='replace', timeout=90)
            print(result.stdout)
            print(result.stderr)
            if result.returncode:
                raise RuntimeError(f'{phase} failed: exit {result.returncode}')
    print('FACTORY_ADDON_LIFECYCLE_OK')


if __name__ == '__main__':
    run()
