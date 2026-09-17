import os
import subprocess

import pytest

from colcon_ros_lake import lake
from colcon_ros_lake import layout

LAKEFILE = """import Lake
open Lake DSL

require rcllean from amentPackage "rcllean"
require «my_msgs» from amentPackage "my_msgs"

package «my_robot» where
  version := v!"0.0.0"

@[default_target]
lean_lib MyRobot where
  roots := #[`MyRobot]

lean_lib Helpers where
  roots := #[`Helpers]

@[default_target]
lean_exe «my-node» where
  root := `MyNode

@[test_driver]
lean_exe tests where
  root := `Main

@[default_target]
input_dir launch

@[default_target]
input_file «my-params.yaml»

input_dir scratch
"""


def test_lakefile_parsing(tmp_path):
    path = tmp_path / 'lakefile.lean'
    path.write_text(LAKEFILE)
    assert lake.package_name(path) == 'my_robot'
    assert lake.required_packages(path) == ['rcllean', 'my_msgs']
    assert lake.library_names(path) == ['MyRobot', 'Helpers']
    assert lake.default_targets(path) == (['MyRobot'], ['my-node'])
    # `scratch` has no attribute, so it is not a default target.
    assert lake.input_targets(path) == [
        ('input_dir', 'launch'), ('input_file', 'my-params.yaml')]
    assert lake.has_test_driver(path)


def test_archive_names_follow_lean_mangling():
    assert layout.archive_name('rcllean', 'Rcllean') == 'rcllean_Rcllean'
    assert layout.archive_name('rcllean_examples', 'RclleanExamples') == \
        'rcllean__examples_RclleanExamples'
    with pytest.raises(ValueError):
        layout.archive_name('my-robot', 'Lib')


def test_install_places_only_what_is_named(tmp_path):
    build = tmp_path / 'build'
    for rel in ('lib/lean/MyRobot.olean', 'lib/lean/MyRobot.ilean',
                'lib/lean/MyRobot/Greeting.olean', 'lib/lean/Main.olean',
                'lib/libmy__robot_MyRobot.a', 'lib/libmy__robot_Helpers.a',
                'lib/libmy__robot_ffi.a'):
        (build / rel).parent.mkdir(parents=True, exist_ok=True)
        (build / rel).write_bytes(b'x')
    (build / 'bin').mkdir()
    for exe in ('my-node', 'tests'):
        (build / 'bin' / exe).write_bytes(b'#!/bin/sh\n')
        os.chmod(build / 'bin' / exe, 0o755)
    prefix = tmp_path / 'install'

    archives = [layout.archive_name('my_robot', 'MyRobot')]
    archives += layout.custom_archives(build, 'my_robot', ['MyRobot', 'Helpers'])
    assert archives == ['my__robot_MyRobot', 'my__robot_ffi']
    layout.install_artifacts(
        build, prefix, 'my_robot',
        modules=['MyRobot', 'MyRobot.Greeting'], archives=archives,
        executables=['my-node'])

    assert (prefix / 'lib/lean/MyRobot.olean').is_file()
    assert (prefix / 'lib/lean/MyRobot/Greeting.olean').is_file()
    assert not (prefix / 'lib/lean/Main.olean').exists()
    assert (prefix / 'lib/libmy__robot_MyRobot.a').is_file()
    assert not (prefix / 'lib/libmy__robot_Helpers.a').exists()
    assert (prefix / 'lib/my_robot/my-node').is_file()
    assert not (prefix / 'lib/my_robot/tests').exists()


def test_hook_exports_stub_and_flags_in_front(tmp_path):
    hook = tmp_path / 'hook.sh'
    hook.write_text(layout.env_hook('my_robot', ['-lmy__robot_MyRobot', '-lrcl']))
    script = f"""
AMENT_LEAN_LINK_ARGS="older"
COLCON_CURRENT_PREFIX=/opt/x
. {hook}
. {hook}
printf '%s\\n' "$AMENT_LEAN_PKG_MY_ROBOT" "$AMENT_LEAN_LINK_ARGS"
"""
    out = subprocess.check_output(['sh', '-c', script]).decode().splitlines()
    assert out[0] == '/opt/x/share/my_robot/lean'
    assert out[1] == '-L/opt/x/lib\t-lmy__robot_MyRobot\t-lrcl\tolder'


def test_stub_requires_dependencies_through_the_environment():
    text = layout.stub_lakefile('my_robot', ['rcllean', 'my_msgs'])
    assert 'require rcllean from amentEnv "AMENT_LEAN_PKG_RCLLEAN"' in text
    assert 'require my_msgs from amentEnv "AMENT_LEAN_PKG_MY_MSGS"' in text
    assert 'package «my_robot»' in text


def test_domain_id_is_stable_and_never_zero():
    assert layout.test_domain_id('rcllean') == layout.test_domain_id('rcllean')
    assert 1 <= layout.test_domain_id('rcllean') <= 101
    assert layout.test_domain_id('rcllean') != layout.test_domain_id('rcllean_examples')


def test_data_files_install_copies_and_replaces(tmp_path):
    source = tmp_path / 'my_robot'
    (source / 'launch').mkdir(parents=True)
    (source / 'launch' / 'talker.launch.py').write_text('launch\n')
    (source / 'config').mkdir()
    (source / 'config' / 'params.yaml').write_text('a: 1\n')
    prefix = tmp_path / 'install'
    share = prefix / 'share' / 'my_robot'
    # A stale file from an earlier build, in the place of a new one.
    (share / 'launch').mkdir(parents=True)
    (share / 'launch' / 'talker.launch.py').write_text('old\n')

    installed = layout.install_data_files(
        source, prefix, 'my_robot', [
            ('launch', str(source / 'launch' / 'talker.launch.py')),
            ('config', str(source / 'config' / 'params.yaml'))])

    assert installed == [
        share / 'launch' / 'talker.launch.py',
        share / 'config' / 'params.yaml']
    assert (share / 'launch' / 'talker.launch.py').read_text() == 'launch\n'
    assert not (share / 'launch' / 'talker.launch.py').is_symlink()
    assert (share / 'config' / 'params.yaml').read_text() == 'a: 1\n'


def test_data_files_install_symlinks(tmp_path):
    source = tmp_path / 'my_robot'
    (source / 'launch').mkdir(parents=True)
    (source / 'launch' / 'talker.launch.py').write_text('launch\n')
    prefix = tmp_path / 'install'
    share = prefix / 'share' / 'my_robot'
    (share / 'launch').mkdir(parents=True)
    (share / 'launch' / 'talker.launch.py').symlink_to(tmp_path / 'nowhere')

    layout.install_data_files(
        source, prefix, 'my_robot',
        [('launch', str(source / 'launch' / 'talker.launch.py'))],
        symlink=True)

    dst = share / 'launch' / 'talker.launch.py'
    assert dst.is_symlink()
    assert dst.resolve() == (source / 'launch' / 'talker.launch.py').resolve()
    assert dst.read_text() == 'launch\n'


def test_data_files_install_rejects_paths_outside_the_package(tmp_path):
    source = tmp_path / 'my_robot'
    (source / 'launch').mkdir(parents=True)
    outside = tmp_path / 'elsewhere.launch.py'
    outside.write_text('x\n')
    with pytest.raises(ValueError) as excinfo:
        layout.install_data_files(
            source, tmp_path / 'install', 'my_robot',
            [('launch', str(outside))])
    assert 'launch' in str(excinfo.value)
    assert 'my_robot' in str(excinfo.value)
    assert not (tmp_path / 'install').exists()


def test_data_files_install_refuses_the_stub_directory(tmp_path):
    source = tmp_path / 'my_robot'
    (source / 'lean').mkdir(parents=True)
    (source / 'lean' / 'extra.lean').write_text('-- x\n')
    with pytest.raises(ValueError) as excinfo:
        layout.install_data_files(
            source, tmp_path / 'install', 'my_robot',
            [('lean', str(source / 'lean' / 'extra.lean'))])
    assert 'lean' in str(excinfo.value)
    assert 'my_robot' in str(excinfo.value)
    assert not (tmp_path / 'install').exists()


def test_data_files_install_reports_a_missing_file(tmp_path):
    source = tmp_path / 'my_robot'
    source.mkdir()
    with pytest.raises(FileNotFoundError) as excinfo:
        layout.install_data_files(
            source, tmp_path / 'install', 'my_robot',
            [('launch', str(source / 'launch' / 'gone.launch.py'))])
    assert 'my_robot' in str(excinfo.value)
