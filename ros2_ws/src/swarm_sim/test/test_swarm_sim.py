"""Phase 2 unit tests for ``swarm_sim`` — world generation + SITL launch args.

Pure Python, no Gazebo / ArduPilot runtime: the world builder is exercised
against tiny in-repo SDF fixtures, so the suite runs inside the plain
``orynth-base`` image (the real ardupilot_gazebo assets live only in the SITL
image).
"""

from swarm_sim.sitl_launcher import arducopter_command, gz_command, home_for
from swarm_sim.world_builder import (
    FDM_BASE_PORT,
    _model_inner,
    build_world,
    drone_model_block,
)

FAKE_MODEL = """<?xml version="1.0"?>
<sdf version="1.9">
  <model name="iris_with_ardupilot">
    <include><uri>model://iris_with_standoffs</uri></include>
    <plugin name="ArduPilotPlugin" filename="ArduPilotPlugin">
      <fdm_addr>127.0.0.1</fdm_addr>
      <fdm_port_in>9002</fdm_port_in>
    </plugin>
  </model>
</sdf>
"""

FAKE_WORLD = """<?xml version="1.0"?>
<sdf version="1.9">
  <world name="iris_runway">
    <light name="sun"></light>
    <include>
      <uri>model://iris_with_gimbal</uri>
      <pose degrees="true">0 0 0.195 0 0 90</pose>
    </include>
  </world>
</sdf>
"""


def _fixtures(tmp_path):
    model = tmp_path / "model.sdf"
    world = tmp_path / "world.sdf"
    model.write_text(FAKE_MODEL)
    world.write_text(FAKE_WORLD)
    return str(model), str(world)


def test_model_inner_extracts_body():
    inner = _model_inner(FAKE_MODEL)
    assert "<plugin" in inner and "fdm_port_in" in inner
    assert "<model name" not in inner  # the wrapper tag is stripped


def test_drone_model_block_assigns_unique_fdm_port():
    inner = _model_inner(FAKE_MODEL)
    block = drone_model_block(3, 15.0, 0.0, inner)
    assert 'name="drone_3"' in block
    assert f"<fdm_port_in>{FDM_BASE_PORT + 30}</fdm_port_in>" in block
    assert "<pose" in block


def test_build_world_stamps_n_drones(tmp_path):
    model, world = _fixtures(tmp_path)
    sdf = build_world(5, 5.0, model_sdf_path=model, world_template_path=world)
    for i in range(5):
        assert f'name="drone_{i}"' in sdf
        assert f"<fdm_port_in>{FDM_BASE_PORT + 10 * i}</fdm_port_in>" in sdf
    # The template's single demo vehicle is gone; the world is renamed.
    assert "iris_with_gimbal" not in sdf
    assert 'name="orynth_swarm"' in sdf


def test_build_world_rejects_bad_args(tmp_path):
    model, world = _fixtures(tmp_path)
    import pytest

    with pytest.raises(ValueError):
        build_world(0, 5.0, model_sdf_path=model, world_template_path=world)
    with pytest.raises(ValueError):
        build_world(5, 0.0, model_sdf_path=model, world_template_path=world)


def test_home_is_shared_datum():
    # Every SITL instance shares one datum home; in Gazebo the distinct model
    # poses (not the home) produce the per-drone GPS spread the swarm server
    # calibrates from.
    home = home_for()
    assert len(home.split(",")) == 4  # lat,lon,alt,yaw
    assert home_for() == home


def test_arducopter_command_shape():
    gz = arducopter_command(1, gazebo=True)
    assert gz[0] == "arducopter"
    assert "--instance" in gz and gz[gz.index("--instance") + 1] == "1"
    assert gz[gz.index("--model") + 1] == "JSON"
    quad = arducopter_command(0, gazebo=False)
    assert quad[quad.index("--model") + 1] == "quad"


def test_arducopter_command_appends_sysid_file():
    cmd = arducopter_command(2, gazebo=False, sysid_file="/tmp/sysid.parm")
    assert "/tmp/sysid.parm" in cmd[cmd.index("--defaults") + 1]


def test_gz_command_headless_flag():
    assert "-s" not in gz_command("/tmp/w.sdf", headless=False)
    assert "-s" in gz_command("/tmp/w.sdf", headless=True)
