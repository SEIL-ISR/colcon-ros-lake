from pathlib import Path
import time
from xml.sax.saxutils import escape

from colcon_core.logging import colcon_logger
from colcon_core.plugin_system import satisfies_version
from colcon_core.shell import get_command_environment
from colcon_core.task import run
from colcon_core.task import TaskExtensionPoint

from colcon_ros_lake.lake import find_lake
from colcon_ros_lake.lake import has_test_driver
from colcon_ros_lake.lake import LAKEFILE
from colcon_ros_lake.lake import lake_missing_message
from colcon_ros_lake.layout import BUILD_DIR_ENV

logger = colcon_logger.getChild(__name__)


def write_xunit(path, suite, name, *, returncode, seconds, output):
    """One xUnit file with one test case, as `colcon test-result` reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    failed = 1 if returncode else 0
    body = ''
    if returncode:
        body = (
            f'    <failure message="exited with code {returncode}">'
            f'{escape(output)}</failure>\n')
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name="{escape(suite)}" tests="1" failures="{failed}" '
        f'errors="0" time="{seconds:.3f}">\n'
        f'  <testcase name="{escape(name)}" classname="{escape(suite)}" '
        f'time="{seconds:.3f}">\n{body}'
        f'    <system-out>{escape(output)}</system-out>\n'
        '  </testcase>\n'
        '</testsuite>\n')


class LakeTestTask(TaskExtensionPoint):
    """Run `lake test`, then the package's own test executables.

    Each step writes an xUnit file under `<build_base>/test_results/<pkg>`.
    """

    def __init__(self):  # noqa: D107
        super().__init__()
        satisfies_version(TaskExtensionPoint.EXTENSION_POINT_VERSION, '^1.0')

    async def test(self, *, extra_steps=None, build_first=None):  # noqa: D102
        pkg = self.context.pkg
        args = self.context.args
        source_dir = Path(args.path)
        build_dir = Path(args.build_base) / 'lean'
        results = Path(args.build_base) / 'test_results' / pkg.name

        try:
            env = await get_command_environment(
                'test', args.build_base, self.context.dependencies)
        except RuntimeError as e:
            logger.error(str(e))
            return 1
        env = dict(env)
        env[BUILD_DIR_ENV] = str(build_dir)

        lake = find_lake(env)
        if not lake:
            logger.error(lake_missing_message())
            return 1
        if build_first:
            # Test executables are not default targets, so the build task
            # left them alone.
            rc = await run(
                self.context, [lake, 'build'] + list(build_first),
                cwd=str(source_dir), env=env)
            if rc.returncode:
                return rc.returncode

        failed = 0
        if has_test_driver(source_dir / LAKEFILE):
            failed += await self.run_step(
                results / 'lake_test.xunit.xml', 'lake test',
                [lake, 'test'], cwd=str(source_dir), env=env)

        for xunit, name, cmd, cwd in extra_steps or []:
            failed += await self.run_step(xunit, name, cmd, cwd=cwd, env=env)

        return 1 if failed else 0

    async def run_step(self, xunit, name, cmd, *, cwd, env):
        """Run one command and record it; returns 1 on failure."""
        start = time.monotonic()
        completed = await run(
            self.context, cmd, cwd=cwd, env=env, capture_output=True)
        output = (completed.stdout or b'').decode(errors='replace')
        output += (completed.stderr or b'').decode(errors='replace')
        write_xunit(
            xunit, name, self.context.pkg.name,
            returncode=completed.returncode,
            seconds=time.monotonic() - start, output=output)
        if completed.returncode:
            logger.error(f"{name} failed for '{self.context.pkg.name}'")
            return 1
        return 0
