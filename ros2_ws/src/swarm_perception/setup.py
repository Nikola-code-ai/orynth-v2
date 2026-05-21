from setuptools import find_packages, setup

package_name = "swarm_perception"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/perception.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Nikola Markovic",
    maintainer_email="dev.markovic@protonmail.com",
    description="YOLO detection + geolocation.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            # detection_geolocator lands in Phase 3 alongside real YOLO.
            "yolo_detector = swarm_perception.yolo_detector_node:main",
        ],
    },
)
