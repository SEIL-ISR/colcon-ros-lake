"""colcon extension building Lean 4 packages with Lake.

Two package types: `lake`, a directory with a `lakefile.lean`, and
`ros.ament_lake`, a ROS package whose `package.xml` declares the build type
`ament_lake`.  The second installs the ament layout that `ros2 run`, launch
files, the ament index and downstream Lean packages expect.
"""

__version__ = '0.1.0'
