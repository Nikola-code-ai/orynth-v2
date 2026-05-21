from setuptools import find_packages, setup

package_name = "swarm_gcs"

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
    maintainer_email="nikolamarkovic.idea@gmail.com",
    description="Ground control station ROS nodes.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "bandwidth_manager = swarm_gcs.bandwidth_manager_node:main",
            "telemetry_aggregator = swarm_gcs.telemetry_aggregator_node:main",
            "swarm_markers = swarm_gcs.swarm_markers_node:main",
        ],
    },
)
