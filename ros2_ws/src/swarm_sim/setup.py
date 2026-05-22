from setuptools import find_packages, setup

package_name = "swarm_sim"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Nikola Markovic",
    maintainer_email="dev.markovic@protonmail.com",
    description="ArduPilot SITL multi-instance launcher.",
    license="Apache-2.0",
    tests_require=["pytest"],
    # Phase 2: multi-instance SITL launcher + Gazebo swarm-world generator.
    # Both are pure-Python and also run directly (python -m swarm_sim.<mod>).
    entry_points={
        "console_scripts": [
            "sitl_launcher = swarm_sim.sitl_launcher:main",
            "world_builder = swarm_sim.world_builder:main",
        ],
    },
)
