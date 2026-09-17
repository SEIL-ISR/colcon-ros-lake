from colcon_core.dependency_descriptor import DependencyDescriptor
from colcon_core.package_identification import logger
from colcon_core.package_identification import PackageIdentificationExtensionPoint
from colcon_core.plugin_system import satisfies_version

from colcon_ros_lake.lake import LAKEFILE
from colcon_ros_lake.lake import package_name
from colcon_ros_lake.lake import required_packages


class LakePackageIdentification(PackageIdentificationExtensionPoint):
    """Identify plain Lake packages: a `lakefile.lean` without a package.xml.

    A ROS package with a manifest is identified by colcon-ros at a higher
    priority and gets the type `ros.ament_lake` from its build type.
    """

    # colcon-ros identifies at 150; CMake and Python identification at 100.
    PRIORITY = 90

    def __init__(self):  # noqa: D107
        super().__init__()
        satisfies_version(
            PackageIdentificationExtensionPoint.EXTENSION_POINT_VERSION, '^1.0')

    def identify(self, desc):  # noqa: D102
        if desc.type is not None and desc.type != 'lake':
            return
        lakefile = desc.path / LAKEFILE
        if not lakefile.is_file():
            return
        name = package_name(lakefile)
        if not name:
            logger.debug(f"no 'package' declaration in '{lakefile}'")
            return
        desc.type = 'lake'
        if desc.name is None:
            desc.name = name
        desc.dependencies['build'] |= {
            DependencyDescriptor(name) for name in required_packages(lakefile)}
