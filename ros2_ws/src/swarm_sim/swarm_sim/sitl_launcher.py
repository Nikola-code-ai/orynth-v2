"""Multi-instance ArduPilot SITL launcher — Phase 2 (PLAN section I, #5).

Spawns N ``arducopter`` SITL processes for the swarm and, in Gazebo mode, the
Gazebo Harmonic process holding the matching N-drone world. For instance ``i``:

* ``--instance i`` -> MAVLink serial0 TCP on ``5760 + 10*i`` (MAVROS connects
  there) and the SITL UDP port on ``14550 + 10*i``;
* **Gazebo mode** — SITL's JSON backend reaches model ``drone_i``'s
  ArduPilotPlugin on FDM port ``9002 + 10*i``. The plugin reports each model's
  *absolute* world pose, so SITL derives a distinct GPS per drone from one
  shared ``--home`` — the swarm server calibrates a common field frame from
  that GPS spread;
* **pure-SITL mode** — the built-in ``quad`` physics model (no Gazebo,
  headless, what CI runs). The shared home makes every local frame coincide.

Pure Python / standard library only (no ROS) — this is the sim container's
entrypoint. It generates the world, starts Gazebo, starts the SITL processes,
then supervises the group, tearing everything down on SIGINT/SIGTERM or as
soon as any child exits.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

from swarm_sim.world_builder import build_world

#: arducopter is on PATH via docker/sitl.Dockerfile.
ARDUCOPTER_BIN = "arducopter"
#: ArduPilot SITL default-parameter directory inside the SITL image.
DEFAULT_PARAMS_DIR = "/home/apbuild/ardupilot/Tools/autotest/default_params"
#: FCU stream-rate overlay baked in by docker/sitl.Dockerfile.
ORYNTH_PARAMS = "/opt/orynth/sitl-params.parm"

#: World datum — matches iris_runway.sdf <spherical_coordinates>.
DATUM_LAT = -35.363262
DATUM_LON = 149.165237
DATUM_ALT = 584.0
HOME_YAW_DEG = 90.0

_procs: list[tuple[str, subprocess.Popen]] = []
_stop = False


def _on_signal(signum, _frame) -> None:
    global _stop
    _stop = True


def home_for() -> str:
    """The shared world-datum home ``lat,lon,alt,yaw`` for every SITL instance.

    Every instance uses one home. In Gazebo the ArduPilotPlugin already reports
    each model's absolute world pose, so SITL derives a distinct GPS per drone
    from this datum — offsetting the home as well would double-count the spawn
    separation. In pure-SITL the shared home makes every local frame coincide.
    """
    return f"{DATUM_LAT:.7f},{DATUM_LON:.7f},{DATUM_ALT},{HOME_YAW_DEG}"


def _defaults_csv(gazebo: bool) -> str:
    """Comma-separated --defaults param files that actually exist."""
    candidates = [os.path.join(DEFAULT_PARAMS_DIR, "copter.parm")]
    if gazebo:
        candidates.append(os.path.join(DEFAULT_PARAMS_DIR, "gazebo-iris.parm"))
    candidates.append(ORYNTH_PARAMS)
    return ",".join(c for c in candidates if os.path.exists(c))


def arducopter_command(
    index: int, gazebo: bool, sysid_file: str = ""
) -> list[str]:
    """Build the ``arducopter`` argv for SITL instance ``index``.

    ``sysid_file``, when given, is appended to ``--defaults`` so the instance
    boots with a distinct ``SYSID_THISMAV`` (see :func:`main`).
    """
    defaults = _defaults_csv(gazebo)
    if sysid_file:
        defaults = f"{defaults},{sysid_file}" if defaults else sysid_file
    cmd = [
        ARDUCOPTER_BIN,
        "--instance",
        str(index),
        "--defaults",
        defaults,
        "--home",
        home_for(),
        "--serial0",
        "tcp:0:wait",
    ]
    if gazebo:
        # JSON backend -> model drone_i's ArduPilotPlugin (port 9002+10*i).
        cmd += ["--model", "JSON"]
    else:
        cmd += ["--model", "quad", "--speedup", "1"]
    return cmd


def gz_command(world_path: str, headless: bool) -> list[str]:
    """Build the ``gz sim`` argv (``-s`` server-only when headless)."""
    cmd = ["gz", "sim", "-v", "2", "-r", world_path]
    if headless:
        cmd.append("-s")
    return cmd


def _spawn(name: str, cmd: list[str], cwd: str | None = None) -> subprocess.Popen:
    """Start a supervised child in its own process group."""
    print(f"[sitl_launcher] start {name}: {' '.join(cmd)}", file=sys.stderr, flush=True)
    proc = subprocess.Popen(cmd, cwd=cwd, start_new_session=True)
    _procs.append((name, proc))
    return proc


def _terminate_all() -> None:
    """SIGTERM the whole group, escalate to SIGKILL after a grace period."""
    for name, proc in _procs:
        if proc.poll() is None:
            print(f"[sitl_launcher] stopping {name}", file=sys.stderr, flush=True)
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.time() + 8.0
    for _name, proc in _procs:
        try:
            proc.wait(timeout=max(0.0, deadline - time.time()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def main(argv: list[str] | None = None) -> int:
    """Generate the world, start the swarm SITL group, supervise it."""
    global _stop
    parser = argparse.ArgumentParser(description="Launch the Orynth SITL swarm.")
    parser.add_argument("--drones", type=int, default=5)
    parser.add_argument("--spacing", type=float, default=5.0)
    parser.add_argument(
        "--gazebo",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="back SITL with Gazebo (default) or use built-in quad physics",
    )
    parser.add_argument(
        "--headless", action="store_true", help="run Gazebo server-only (no GUI)"
    )
    parser.add_argument("--world", default="/tmp/orynth_swarm.sdf")
    parser.add_argument(
        "--sitl-delay",
        type=float,
        default=12.0,
        help="seconds to wait for Gazebo before starting SITL",
    )
    args = parser.parse_args(argv)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    print(
        f"[sitl_launcher] {args.drones} drones, "
        f"{'Gazebo' if args.gazebo else 'pure-SITL'}"
        f"{' (headless)' if args.headless else ''}",
        file=sys.stderr,
        flush=True,
    )

    if args.gazebo:
        world = build_world(args.drones, args.spacing)
        with open(args.world, "w", encoding="utf-8") as fh:
            fh.write(world)
        print(f"[sitl_launcher] wrote world -> {args.world}", file=sys.stderr, flush=True)
        _spawn("gazebo", gz_command(args.world, args.headless))
        time.sleep(args.sitl_delay)  # let Gazebo load models + bind FDM ports

    for i in range(args.drones):
        if _stop:
            break
        workdir = f"/tmp/orynth_sitl/drone_{i}"
        os.makedirs(workdir, exist_ok=True)
        # Distinct MAVLink system id per vehicle (SYSID_THISMAV = i + 1).
        # MAVROS derives its /uas<id> router prefix from the system id; a
        # shared id collides across instances and kills one MAVROS node.
        sysid_file = os.path.join(workdir, "sysid.parm")
        with open(sysid_file, "w", encoding="utf-8") as fh:
            fh.write(f"SYSID_THISMAV {i + 1}\n")
        _spawn(
            f"sitl_drone_{i}",
            arducopter_command(i, args.gazebo, sysid_file),
            cwd=workdir,
        )
        time.sleep(0.5)  # stagger so the FDM handshakes do not race

    print("[sitl_launcher] swarm up — supervising", file=sys.stderr, flush=True)
    while not _stop:
        time.sleep(1.0)
        for name, proc in _procs:
            if proc.poll() is not None:
                print(
                    f"[sitl_launcher] {name} exited rc={proc.returncode} "
                    "— tearing down swarm",
                    file=sys.stderr,
                    flush=True,
                )
                _stop = True
                break

    _terminate_all()
    print("[sitl_launcher] swarm down", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
