from pathlib import Path
import subprocess

from colcon_core.logging import colcon_logger
from colcon_core.plugin_system import satisfies_version
from colcon_core.shell import create_environment_hook
from colcon_core.task import create_file
from colcon_core.task import install
from colcon_core.task import TaskExtensionPoint

from colcon_ros_lake.lake import input_files
from colcon_ros_lake.lake import input_targets
from colcon_ros_lake.lake import LAKEFILE
from colcon_ros_lake.layout import install_data_files
from colcon_ros_lake.task.lake.build import LakeBuildTask

logger = colcon_logger.getChild(__name__)


class AmentLakeBuildTask(TaskExtensionPoint):
    """Build ROS packages with the build type 'ament_lake'.

    The Lake build and the Lean layout come from the `lake` task; this adds
    what makes the result an ament package: the manifest, the package index
    marker, the AMENT_PREFIX_PATH hook, and the files the lakefile's default
    input targets match.
    """

    def __init__(self):  # noqa: D107
        super().__init__()
        satisfies_version(TaskExtensionPoint.EXTENSION_POINT_VERSION, '^1.0')

    # `--lake-args` is registered once, by the `lake` task; the parser is
    # shared, so it reaches this task through the same context.

    async def build(self):  # noqa: D102
        pkg = self.context.pkg
        args = self.context.args
        logger.info(
            f"Building ROS package in '{args.path}' with build type "
            "'ament_lake'")

        extension = LakeBuildTask()
        extension.set_context(context=self.context)

        hooks = create_environment_hook(
            'ament_prefix_path', Path(args.install_base), pkg.name,
            'AMENT_PREFIX_PATH', '', mode='prepend')
        create_file(
            args, f'share/ament_index/resource_index/packages/{pkg.name}')
        install(args, 'package.xml', f'share/{pkg.name}/package.xml')

        rc = await extension.build(additional_hooks=hooks)
        if rc:
            return rc

        # Only after the build: `lake query` loads the workspace, which
        # resolves this package's dependencies.
        names = [name for _, name in input_targets(Path(args.path) / LAKEFILE)]
        try:
            files = input_files(
                extension.lake, args.path, names, extension.env)
        except subprocess.CalledProcessError as e:
            logger.error(
                f"'{pkg.name}': {' '.join(e.cmd)} failed with "
                f'{e.returncode}\n' + (e.stderr or b'').decode(errors='replace'))
            return 1
        try:
            install_data_files(
                args.path, args.install_base, pkg.name, files,
                symlink=args.symlink_install)
        except (ValueError, OSError) as e:
            logger.error(str(e))
            return 1
        return 0
