from pathlib import Path

from colcon_core.environment import create_environment_scripts
from colcon_core.logging import colcon_logger
from colcon_core.plugin_system import satisfies_version
from colcon_core.shell import create_environment_hook
from colcon_core.shell import get_command_environment
from colcon_core.task import run
from colcon_core.task import TaskExtensionPoint

from colcon_ros_lake.lake import default_targets
from colcon_ros_lake.lake import find_lake
from colcon_ros_lake.lake import LAKEFILE
from colcon_ros_lake.lake import lake_missing_message
from colcon_ros_lake.lake import library_modules
from colcon_ros_lake.lake import library_names
from colcon_ros_lake.lake import required_packages
from colcon_ros_lake.layout import archive_link_flags
from colcon_ros_lake.layout import archive_name
from colcon_ros_lake.layout import BUILD_DIR_ENV
from colcon_ros_lake.layout import custom_archives
from colcon_ros_lake.layout import env_hook
from colcon_ros_lake.layout import extra_link_flags
from colcon_ros_lake.layout import install_artifacts
from colcon_ros_lake.layout import package_env_var
from colcon_ros_lake.layout import write_stub

logger = colcon_logger.getChild(__name__)


class LakeBuildTask(TaskExtensionPoint):
    """Build a Lake package and install it into the prefix.

    Lake writes its output under `<build_base>/lean`, not into the source
    tree.  The installed layout is the one `colcon_ros_lake.layout`
    describes; a package's Lean dependencies reach it through the environment
    hooks their own installs registered.

    After a successful build, `lake` and `env` hold what the build ran with,
    so another task can invoke Lake in the same workspace.
    """

    def __init__(self):  # noqa: D107
        super().__init__()
        satisfies_version(TaskExtensionPoint.EXTENSION_POINT_VERSION, '^1.0')
        self.lake = None
        self.env = None

    def add_arguments(self, *, parser):  # noqa: D102
        parser.add_argument(
            '--lake-args', nargs='*', metavar='*', type=str.lstrip,
            help='Pass arguments to `lake build`. Arguments matching other '
                 'options must be prefixed by a space, e.g. '
                 '--lake-args " --verbose"')

    async def build(self, *, additional_hooks=None):  # noqa: D102
        pkg = self.context.pkg
        args = self.context.args
        source_dir = Path(args.path)
        build_dir = Path(args.build_base) / 'lean'
        prefix = Path(args.install_base)

        logger.info(f"Building Lake package in '{args.path}'")

        try:
            env = await get_command_environment(
                'build', args.build_base, self.context.dependencies)
        except RuntimeError as e:
            logger.error(str(e))
            return 1
        lake = find_lake(env)
        if not lake:
            logger.error(lake_missing_message())
            return 1
        env = dict(env)
        env[BUILD_DIR_ENV] = str(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)
        self.lake = lake
        self.env = env

        # The dependencies installed as Lean packages, as this package's
        # lakefile names them.  Their stub directories moved with the
        # prefix, so the manifest entries are refreshed before the build.
        lean_deps = [
            name for name in required_packages(source_dir / LAKEFILE)
            if env.get(package_env_var(name))]
        if lean_deps:
            rc = await run(
                self.context, [lake, 'update'] + lean_deps,
                cwd=str(source_dir), env=env)
            if rc.returncode:
                return rc.returncode

        # What gets installed is what the lakefile marks as a default
        # target; `lake build` alone does not produce a library's archive.
        libs, exes = default_targets(source_dir / LAKEFILE)
        cmd = [lake, 'build'] + [f'{lib}:static' for lib in libs] + exes
        cmd += args.lake_args or []
        rc = await run(self.context, cmd, cwd=str(source_dir), env=env)
        if rc.returncode:
            return rc.returncode

        modules = []
        for lib in libs:
            modules += library_modules(lake, source_dir, lib, env=env)
        archives = [archive_name(pkg.name, lib) for lib in libs]
        archives += custom_archives(
            build_dir, pkg.name, library_names(source_dir / LAKEFILE))
        install_artifacts(
            build_dir, prefix, pkg.name, modules=modules, archives=archives,
            executables=exes, symlink=args.symlink_install)

        toolchain = source_dir / 'lean-toolchain'
        if not toolchain.is_file():
            logger.error(
                f"'{pkg.name}' has no lean-toolchain file.  A .olean is "
                'tied to the compiler that produced it, so a package built '
                'for others to import has to pin its toolchain.')
            return 1
        write_stub(
            prefix / 'share' / pkg.name / 'lean', pkg.name, lean_deps,
            toolchain)

        hooks = create_environment_hook(
            'lean_path', prefix, pkg.name, 'LEAN_PATH', 'lib/lean',
            mode='prepend')
        hook = prefix / 'share' / pkg.name / 'hook' / 'ament_lean.sh'
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(env_hook(
            pkg.name,
            archive_link_flags(archives) + extra_link_flags(build_dir)))
        hooks.append(hook)
        if additional_hooks:
            hooks += additional_hooks

        create_environment_scripts(pkg, args, additional_hooks=hooks)
        return 0
