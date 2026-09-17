"""`lake-ament-build`: the Lean install layout, from outside colcon.

`rosidl_generator_lean` runs inside an interface package's CMake build, where
there is no colcon task to do the work.  It calls these subcommands instead,
so an interface package's Lean bindings land in the same layout an
`ament_lake` package gets.
"""

import argparse
import os
from pathlib import Path
import subprocess
import sys

from colcon_ros_lake.lake import default_targets
from colcon_ros_lake.lake import find_lake
from colcon_ros_lake.lake import LAKEFILE
from colcon_ros_lake.lake import lake_missing_message
from colcon_ros_lake.lake import library_modules
from colcon_ros_lake.lake import library_names
from colcon_ros_lake.layout import archive_link_flags
from colcon_ros_lake.layout import archive_name
from colcon_ros_lake.layout import BUILD_DIR_ENV
from colcon_ros_lake.layout import custom_archives
from colcon_ros_lake.layout import env_hook
from colcon_ros_lake.layout import extra_link_flags
from colcon_ros_lake.layout import install_artifacts
from colcon_ros_lake.layout import write_stub


def _lake_env(build_dir):
    lake = find_lake()
    if not lake:
        sys.stderr.write(lake_missing_message() + '\n')
        sys.exit(1)
    env = dict(os.environ)
    env[BUILD_DIR_ENV] = str(Path(build_dir).resolve())
    return lake, env


def cmd_build(args):
    """Build the default targets, libraries as archives."""
    lake, env = _lake_env(args.build_dir)
    if args.update:
        rc = subprocess.call(
            [lake, 'update'] + args.update, cwd=args.source_dir, env=env)
        if rc:
            return rc
    libs, exes = default_targets(Path(args.source_dir) / LAKEFILE)
    targets = [f'{lib}:static' for lib in libs] + exes + args.targets
    return subprocess.call(
        [lake, 'build'] + targets, cwd=args.source_dir, env=env)


def cmd_install(args):
    """Copy the default targets' output into the prefix."""
    lake, env = _lake_env(args.build_dir)
    lakefile = Path(args.source_dir) / LAKEFILE
    libs, exes = default_targets(lakefile)
    modules = []
    for lib in libs:
        modules += library_modules(lake, args.source_dir, lib, env=env)
    archives = [archive_name(args.package, lib) for lib in libs]
    archives += custom_archives(
        args.build_dir, args.package, library_names(lakefile))
    install_artifacts(
        args.build_dir, args.install_base, args.package, modules=modules,
        archives=archives, executables=exes)
    return 0


def cmd_stub(args):
    """Write the stub Lake package for an installed package."""
    write_stub(args.out, args.package, args.dependency, args.toolchain)
    return 0


def cmd_hook(args):
    """Write the environment hook for an installed package.

    Before the build, the archives are named from `--library`; after it,
    `--build-dir` lists what was built.
    """
    flags = archive_link_flags(
        archive_name(args.package, lib) for lib in args.library)
    if args.build_dir:
        flags += extra_link_flags(args.build_dir)
    flags += args.link_arg
    # A static archive only resolves symbols still undefined to its left, so
    # a repeated flag keeps its first position.
    seen = []
    for flag in flags:
        if flag not in seen:
            seen.append(flag)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(env_hook(args.package, seen))
    return 0


def main(argv=None):
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        prog='lake-ament-build', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('build', help='run lake build into a build directory')
    p.add_argument('--source-dir', required=True)
    p.add_argument('--build-dir', required=True)
    p.add_argument('--update', action='append', default=[], metavar='DEP',
                   help='run `lake update DEP` first')
    p.add_argument('targets', nargs='*')
    p.set_defaults(func=cmd_build)

    p = sub.add_parser('install', help='copy the output into a prefix')
    p.add_argument('--package', required=True)
    p.add_argument('--source-dir', required=True)
    p.add_argument('--build-dir', required=True)
    p.add_argument('--install-base', required=True)
    p.set_defaults(func=cmd_install)

    p = sub.add_parser('stub', help='write the installed stub package')
    p.add_argument('--package', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--toolchain', required=True)
    p.add_argument('--dependency', action='append', default=[])
    p.set_defaults(func=cmd_stub)

    p = sub.add_parser('hook', help='write the environment hook')
    p.add_argument('--package', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--library', action='append', default=[])
    p.add_argument('--build-dir')
    p.add_argument('--link-arg', action='append', default=[])
    p.set_defaults(func=cmd_hook)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
