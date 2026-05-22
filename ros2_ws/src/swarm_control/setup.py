from setuptools import find_packages, setup

package_name = "swarm_control"

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
    description="Backend-neutral swarm control.",
    license="Apache-2.0",
    tests_require=["pytest"],
    # Phase 1: sitl_mission drives the single-drone SITL acceptance run.
    # swarm_server lands in Phase 2.
    entry_points={
        "console_scripts": [
            "sitl_mission = swarm_control.sitl_mission:main",
        ],
    },
)
