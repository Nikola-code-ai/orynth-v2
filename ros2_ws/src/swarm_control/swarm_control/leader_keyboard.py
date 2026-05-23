"""Keyboard teleop for the swarm leader (drone_0).

Each keypress reads drone_0's current field-frame position from
``/swarm/status`` and calls ``/swarm/drone_0/manual_goto`` with
``current + delta``. The ``/swarm/follow_leader`` loop, if engaged, drags
the four followers along.

Run inside the companion container, after the swarm is up and
``/swarm/follow_leader`` has engaged::

    ros2 run swarm_control leader_keyboard
"""

from __future__ import annotations

import select
import sys
import termios
import tty
from dataclasses import dataclass

import rclpy
from rclpy.node import Node
from swarm_msgs.msg import SwarmStatus
from swarm_msgs.srv import ManualGoto

HELP = """
Leader keyboard teleop — drone_0 (ENU field frame)
  w / W : north +2 m / +5 m       s / S : south
  a / A : west  +2 m / +5 m       d / D : east
  r / R : up    +1 m / +2 m       f / F : down
  space : hold (re-send current pose as target)
  h     : show this help
  q / Ctrl-C : quit
"""


@dataclass(frozen=True)
class Step:
    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0


KEYS: dict[str, Step] = {
    "w": Step(dy=2.0),   "W": Step(dy=5.0),
    "s": Step(dy=-2.0),  "S": Step(dy=-5.0),
    "a": Step(dx=-2.0),  "A": Step(dx=-5.0),
    "d": Step(dx=2.0),   "D": Step(dx=5.0),
    "r": Step(dz=1.0),   "R": Step(dz=2.0),
    "f": Step(dz=-1.0),  "F": Step(dz=-2.0),
    " ": Step(),
}


class LeaderKeyboard(Node):
    def __init__(self) -> None:
        super().__init__("leader_keyboard")
        self._leader_pos: tuple[float, float, float] | None = None
        self.create_subscription(SwarmStatus, "/swarm/status", self._on_status, 10)
        self._client = self.create_client(ManualGoto, "/swarm/drone_0/manual_goto")
        self.create_timer(1.0 / 30.0, self._tick)
        self.get_logger().info(HELP)
        if not self._client.wait_for_service(timeout_sec=10.0):
            self.get_logger().warning(
                "/swarm/drone_0/manual_goto not available — keypresses "
                "will be ignored until swarm_server appears",
            )

    def _on_status(self, msg: SwarmStatus) -> None:
        if not msg.drones:
            return
        p = msg.drones[0].pose.pose.position
        self._leader_pos = (p.x, p.y, p.z)

    def _tick(self) -> None:
        if not select.select([sys.stdin], [], [], 0.0)[0]:
            return
        ch = sys.stdin.read(1)
        if ch in ("q", "\x03"):
            rclpy.shutdown()
            return
        if ch == "h":
            self.get_logger().info(HELP)
            return
        step = KEYS.get(ch)
        if step is None:
            return
        if self._leader_pos is None:
            self.get_logger().warning(
                "no /swarm/status yet — is the swarm up and follow_leader engaged?",
            )
            return
        x, y, z = self._leader_pos
        req = ManualGoto.Request()
        req.target.x = x + step.dx
        req.target.y = y + step.dy
        req.target.z = z + step.dz
        future = self._client.call_async(req)
        future.add_done_callback(self._on_response)
        self.get_logger().info(
            f"-> field ({req.target.x:.1f}, {req.target.y:.1f}, {req.target.z:.1f})",
        )

    def _on_response(self, future) -> None:
        try:
            resp = future.result()
        except Exception as exc:  # noqa: BLE001 — surface as a teleop warning
            self.get_logger().error(f"manual_goto raised: {exc!r}")
            return
        if not resp.success:
            self.get_logger().warning(f"manual_goto rejected: {resp.message}")


def main() -> None:
    rclpy.init()
    node = LeaderKeyboard()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
