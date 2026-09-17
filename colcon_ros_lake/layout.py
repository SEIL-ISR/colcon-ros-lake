"""The ament install layout of a Lean package, and the environment it needs.

Shared by the `ament_lake` build task and the `lake-ament-build` command that
`rosidl_generator_lean` runs from CMake, so both produce the same prefix:

  lib/lean/                 .olean and .ilean files, on LEAN_PATH
  lib/lib<pkg>_<Lib>.a      object code, one archive per lean_lib
  lib/<pkg>/<exe>           executables, where `ros2 run` looks
  share/<pkg>/lean/         a stub Lake package a downstream can `require`
  share/<pkg>/hook/         environment hooks

A lakefile learns about this layout only through the environment:

  AMENT_LEAN_BUILD_DIR      where Lake writes output (set for the build)
  AMENT_LEAN_PKG_<PKG>      the stub directory of an installed dependency
  AMENT_LEAN_LINK_ARGS      tab-separated linker flags for every dependency

The hooks export the last two, so a bare `lake build` in a sourced workspace
sees what a colcon build sees.
"""

import hashlib
from pathlib import Path
import re
import shutil

BUILD_DIR_ENV = 'AMENT_LEAN_BUILD_DIR'
LINK_ARGS_ENV = 'AMENT_LEAN_LINK_ARGS'
# Separator for LINK_ARGS_ENV: a flag may carry a path with spaces.
LINK_ARGS_SEP = '\t'
# A lakefile that links against libraries outside the workspace writes the
# flags a downstream needs, one per line, to this file in its build dir.
EXTRA_LINK_ARGS_FILE = 'ament_link_args'
# The stub package's directory under share/<pkg>; not free for data files.
STUB_DIR = 'lean'

_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def package_env_var(pkg_name):
    """Name of the variable holding an installed package's stub directory."""
    return 'AMENT_LEAN_PKG_' + pkg_name.upper()


def mangle(name):
    """Lean's C name mangling for one identifier: `_` becomes `__`."""
    if not _IDENT.fullmatch(name):
        raise ValueError(
            f"'{name}' is not a plain identifier; the archive name it would "
            'get involves escapes this tool does not reproduce')
    return name.replace('_', '__')


def archive_name(pkg_name, lib_name):
    """Return the base name of the archive Lake builds for a lean_lib."""
    return f'{mangle(pkg_name)}_{mangle(lib_name)}'


def archive_link_flags(archives):
    """Return `-l` flags for a list of archive base names."""
    return ['-l' + name for name in archives]


def extra_link_flags(build_dir):
    """Return the flags the lakefile exported in EXTRA_LINK_ARGS_FILE."""
    path = Path(build_dir) / EXTRA_LINK_ARGS_FILE
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text().splitlines()
            if line.strip()]


def _clear(dst):
    """Remove a destination left by an earlier install."""
    if dst.is_symlink():
        dst.unlink()
    elif dst.is_dir():
        shutil.rmtree(dst)
    elif dst.exists():
        dst.unlink()


def _place(src, dst, symlink):
    """Install one file, replacing whatever an earlier build left there."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _clear(dst)
    if symlink:
        dst.symlink_to(src.resolve())
    else:
        shutil.copy2(src, dst)


def install_artifacts(build_dir, install_base, pkg_name, *, modules,
                      archives, executables, symlink=False):
    """Copy what Lake built into the ament layout.

    `modules` are Lean module names, `archives` base names without the
    `lib` prefix and `.a` suffix, `executables` names under `bin/`.
    Returns the list of destination paths.
    """
    build_dir = Path(build_dir)
    install_base = Path(install_base)
    installed = []

    lean_dir = build_dir / 'lib' / 'lean'
    for module in modules:
        rel = Path(*module.split('.'))
        for suffix in ('.olean', '.ilean'):
            src = lean_dir / rel.with_suffix(suffix)
            # An .ilean is only for the editor; a module built without one is
            # not an error.
            if not src.is_file():
                continue
            dst = install_base / 'lib' / 'lean' / rel.with_suffix(suffix)
            _place(src, dst, symlink)
            installed.append(dst)

    for archive in archives:
        src = build_dir / 'lib' / f'lib{archive}.a'
        if not src.is_file():
            raise FileNotFoundError(f'{src}: not built')
        dst = install_base / 'lib' / src.name
        _place(src, dst, symlink)
        installed.append(dst)

    for exe in executables:
        src = build_dir / 'bin' / exe
        if not src.is_file():
            raise FileNotFoundError(f'{src}: not built')
        dst = install_base / 'lib' / pkg_name / exe
        _place(src, dst, symlink)
        installed.append(dst)

    return installed


def install_data_files(source_dir, install_base, pkg_name, files, *,
                       symlink=False):
    """Install a package's input-target files under `share/<pkg>/`.

    `files` are `(target, absolute path)` pairs, as `lake.input_files`
    returns them.  Each file keeps the path it has relative to the package
    root, so `launch/talker.launch.py` lands at
    `share/<pkg>/launch/talker.launch.py`.  Returns the destination paths.
    """
    root = Path(source_dir).resolve()
    share = Path(install_base) / 'share' / pkg_name
    installed = []
    for target, path in files:
        src = Path(path)
        if not src.is_absolute():
            src = Path(source_dir) / src
        try:
            rel = src.resolve().relative_to(root)
        except ValueError:
            raise ValueError(
                f"input target '{target}' of package '{pkg_name}': "
                f'{path} is outside the package directory '
                f'{root}') from None
        if rel.parts[0] == STUB_DIR:
            raise ValueError(
                f"input target '{target}' of package '{pkg_name}': "
                f'share/{pkg_name}/{STUB_DIR} holds the generated '
                'stub package; pick another path')
        if not src.is_file():
            raise FileNotFoundError(
                f"input target '{target}' of package '{pkg_name}': "
                f'{path} is not a file')
        _place(src, share / rel, symlink)
        installed.append(share / rel)
    return installed


def custom_archives(build_dir, pkg_name, known_libs):
    """Return the archives under `lib/` that no lean_lib produced.

    A lakefile may build its own archive, a C shim for instance.  A
    downstream links against it too, so it is installed and gets a `-l` flag
    in the hook.
    """
    lib_dir = Path(build_dir) / 'lib'
    if not lib_dir.is_dir():
        return []
    lib_archives = {archive_name(pkg_name, lib) for lib in known_libs}
    return sorted(
        p.name[3:-2] for p in lib_dir.glob('lib*.a')
        if p.name[3:-2] not in lib_archives)


def stub_lakefile(pkg_name, dependencies):
    """Return the lakefile of the installed stub package.

    It declares no targets: it points Lake at this prefix's `lib/lean`, so a
    downstream `require` resolves the modules without a rebuild, and it
    re-requires this package's own Lean dependencies so the downstream only
    lists what it imports directly.
    """
    requires = ''.join(
        f'require {dep} from amentEnv "{package_env_var(dep)}"\n'
        for dep in dependencies)
    return f"""import Lake
open Lake DSL

/-! Stub Lake package for the installed ament package `{pkg_name}`.

Generated by colcon-ros-lake.  Builds nothing; it makes this prefix's
`lib/lean` part of a downstream workspace's module search path.
-/

private unsafe def envImpl (key : String) : String :=
  match unsafeBaseIO (IO.getEnv key) with
  | some v => v
  | none => ""

@[implemented_by envImpl]
opaque amentEnv (key : String) : String

{requires}package «{pkg_name}» where
  -- This file is in `<prefix>/share/{pkg_name}/lean`; three levels up is
  -- the install prefix.
  buildDir := "../../.."
  leanLibDir := "lib/lean"
  nativeLibDir := "lib"
  binDir := "lib/{pkg_name}"
"""


def stub_manifest(pkg_name):
    """Return a manifest for the stub, so Lake never writes one there."""
    return (
        '{"version": "1.2.0",\n'
        ' "packagesDir": ".lake/packages",\n'
        ' "packages": [],\n'
        f' "name": "{pkg_name}",\n'
        ' "lakeDir": ".lake",\n'
        ' "fixedToolchain": false}\n')


def write_stub(out_dir, pkg_name, dependencies, toolchain_file):
    """Write the stub package: lakefile, manifest, and the toolchain pin.

    A `.olean` is tied to the compiler that produced it, so the pin travels
    with the package for whoever builds against it.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'lakefile.lean').write_text(
        stub_lakefile(pkg_name, dependencies))
    (out_dir / 'lake-manifest.json').write_text(stub_manifest(pkg_name))
    shutil.copy2(toolchain_file, out_dir / 'lean-toolchain')
    return out_dir


def env_hook(pkg_name, link_flags):
    """Return the sh hook exporting the stub directory and link flags.

    colcon sources a hook with COLCON_CURRENT_PREFIX set; ament's
    local_setup.sh sets AMENT_CURRENT_PREFIX.  This package's flags go in
    front: a package is sourced after its dependencies, and a static archive
    only resolves symbols still undefined to its left.
    """
    var = package_env_var(pkg_name)
    flags = LINK_ARGS_SEP.join(['-L$_ament_lean_prefix/lib'] + list(link_flags))
    return f"""# generated by colcon-ros-lake for the Lean package '{pkg_name}'

if [ -n "${{COLCON_CURRENT_PREFIX:-}}" ]; then
  _ament_lean_prefix="$COLCON_CURRENT_PREFIX"
else
  _ament_lean_prefix="$AMENT_CURRENT_PREFIX"
fi

{var}="$_ament_lean_prefix/share/{pkg_name}/lean"
export {var}

_ament_lean_args="{flags}"
case "${{{LINK_ARGS_ENV}:-}}" in
  *"$_ament_lean_args"*)
    ;;
  "")
    {LINK_ARGS_ENV}="$_ament_lean_args"
    ;;
  *)
    {LINK_ARGS_ENV}="$_ament_lean_args{LINK_ARGS_SEP}${LINK_ARGS_ENV}"
    ;;
esac
export {LINK_ARGS_ENV}
unset _ament_lean_args
unset _ament_lean_prefix
"""


def test_domain_id(pkg_name):
    """Pick a ROS_DOMAIN_ID for a package's tests: stable, per package, not 0.

    ROS 2 documents 0 through 101 as the portable range; 0 is what everything
    else on the host defaults to.
    """
    digest = hashlib.md5(pkg_name.encode()).hexdigest()
    return int(digest[:6], 16) % 101 + 1
