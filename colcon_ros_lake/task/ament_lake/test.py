import os
from pathlib import Path

from catkin_pkg.package import parse_package
from colcon_core.logging import colcon_logger
from colcon_core.plugin_system import satisfies_version
from colcon_core.task import TaskExtensionPoint

from colcon_ros_lake.layout import test_domain_id
from colcon_ros_lake.task.lake.test import LakeTestTask

logger = colcon_logger.getChild(__name__)

# A package lists executables that need the middleware in its manifest:
#   <export><lean_test_executable>test-topics</lean_test_executable></export>
# Each runs from the build directory on a ROS_DOMAIN_ID of its own.
TEST_EXPORT = 'lean_test_executable'
TEST_TIMEOUT = '180'


class AmentLakeTestTask(TaskExtensionPoint):
    """Test ROS packages with the build type 'ament_lake'."""

    def __init__(self):  # noqa: D107
        super().__init__()
        satisfies_version(TaskExtensionPoint.EXTENSION_POINT_VERSION, '^1.0')

    async def test(self):  # noqa: D102
        pkg = self.context.pkg
        args = self.context.args
        build_dir = Path(args.build_base) / 'lean'
        results = Path(args.build_base) / 'test_results' / pkg.name

        manifest = parse_package(args.path)
        exes = [e.content.strip() for e in manifest.exports
                if e.tagname == TEST_EXPORT]
        domain = os.environ.get('ROS_DOMAIN_ID') or str(test_domain_id(pkg.name))
        if exes:
            logger.info(f"'{pkg.name}' tests run on ROS_DOMAIN_ID={domain}")

        steps = [
            (results / f'{exe}.xunit.xml', exe,
             ['env', f'ROS_DOMAIN_ID={domain}', 'timeout', TEST_TIMEOUT,
              str(build_dir / 'bin' / exe)],
             str(build_dir))
            for exe in exes]

        extension = LakeTestTask()
        extension.set_context(context=self.context)
        return await extension.test(extra_steps=steps, build_first=exes)
