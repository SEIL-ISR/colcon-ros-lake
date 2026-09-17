"""Finding and invoking Lake."""

import os
from pathlib import Path
import re
import shutil
import subprocess

LAKEFILE = 'lakefile.lean'
# Kinds of `@[default_target]` declaration whose files are installed as data.
INPUT_KINDS = ('input_dir', 'input_file')
# The lakefile is Lean source, read here by regex.  Evaluating it needs a
# Lake workspace, and colcon needs the package name and its requires before
# there is an environment to build one in.
_PACKAGE_DECL = re.compile(r'^package\s+(?:«([^»]+)»|([A-Za-z_][\w.]*))', re.M)
_REQUIRE_DECL = re.compile(r'^require\s+(?:«([^»]+)»|([A-Za-z_][\w.]*))', re.M)
_LIB_DECL = re.compile(r'^lean_lib\s+(?:«([^»]+)»|([A-Za-z_][\w.]*))', re.M)
_DEFAULT_DECL = re.compile(
    r'^@\[[^\]]*default_target[^\]]*\]\s*\n'
    r'(lean_lib|lean_exe|input_dir|input_file)\s+'
    r'(?:«([^»]+)»|([A-Za-z_][\w.]*))', re.M)


def find_lake(env=None):
    """Path to `lake`: on PATH, then under elan's home."""
    env = os.environ if env is None else env
    found = shutil.which('lake', path=env.get('PATH'))
    if found:
        return found
    for home in (env.get('ELAN_HOME'), os.path.join(env.get('HOME', ''), '.elan')):
        if home and os.access(os.path.join(home, 'bin', 'lake'), os.X_OK):
            return os.path.join(home, 'bin', 'lake')
    return None


def lake_missing_message():
    """Explain what to do when no Lake is found."""
    return (
        'lake was not found on PATH or under $HOME/.elan/bin.  Install the '
        'Lean 4 toolchain with elan (https://github.com/leanprover/elan) and '
        'make sure lake is on PATH when colcon runs, for example by sourcing '
        '$HOME/.elan/env.')


def package_name(lakefile):
    """Return the name a lakefile declares, or None."""
    text = Path(lakefile).read_text()
    m = _PACKAGE_DECL.search(text)
    if not m:
        return None
    return m.group(1) or m.group(2)


def required_packages(lakefile):
    """Return the names a lakefile `require`s."""
    text = Path(lakefile).read_text()
    return [m.group(1) or m.group(2) for m in _REQUIRE_DECL.finditer(text)]


def library_names(lakefile):
    """Return the `lean_lib` targets a lakefile declares.

    `lake build` compiles a library's modules but not its static archive
    unless `<lib>:static` is asked for, and the archive is what a downstream
    links against.
    """
    text = Path(lakefile).read_text()
    return [m.group(1) or m.group(2) for m in _LIB_DECL.finditer(text)]


def _default_decls(lakefile):
    """Yield `(kind, name)` for every `@[default_target]` declaration."""
    text = Path(lakefile).read_text()
    for m in _DEFAULT_DECL.finditer(text):
        yield m.group(1), m.group(2) or m.group(3)


def default_targets(lakefile):
    """Return the `@[default_target]` libraries and executables.

    These are what a package offers: `lake build` builds them, and they are
    what gets installed.  Test drivers, harnesses and tools without the
    attribute stay in the build directory.
    """
    libs, exes = [], []
    for kind, name in _default_decls(lakefile):
        if kind == 'lean_lib':
            libs.append(name)
        elif kind == 'lean_exe':
            exes.append(name)
    return libs, exes


def input_targets(lakefile):
    """Return the `@[default_target]` input targets as `(kind, name)` pairs.

    Their files are what the package installs under `share/<pkg>`.  An input
    target without the attribute is not a default target and not installed.
    """
    return [(kind, name) for kind, name in _default_decls(lakefile)
            if kind in INPUT_KINDS]


def library_modules(lake, source_dir, lib, env=None):
    """Return the modules of a library, from `lake query`."""
    # Progress goes to stderr; only stdout carries the module names.
    out = subprocess.check_output(
        [lake, 'query', '--text', f'{lib}:modules'],
        cwd=str(source_dir), env=env, stderr=subprocess.DEVNULL)
    return [line.strip() for line in out.decode().splitlines()
            if line.strip()]


def input_files(lake, source_dir, names, env=None):
    """Return `(target, absolute path)` for every file the input targets match.

    One `lake query` per name: a query over several names prints their files
    with nothing to say which target matched which.  Run this after the
    build, Lake resolves the package's dependencies when it loads the
    workspace, so it needs the build environment and cwd.
    """
    found = []
    for name in names:
        # Progress goes to stderr; only stdout carries the paths.
        done = subprocess.run(
            [lake, 'query', '--text', name], cwd=str(source_dir), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        found += [(name, line.strip())
                  for line in done.stdout.decode().splitlines()
                  if line.strip()]
    return found


def has_test_driver(lakefile):
    """Whether the lakefile declares something `lake test` can run."""
    return '@[test_driver]' in Path(lakefile).read_text()
