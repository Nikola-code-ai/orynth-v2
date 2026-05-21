"""YOLO detector node.

Phase 0: passthrough (publishes empty detection arrays) to fix v1 mistake #2 —
this package ships with a real package.xml + working node from day one.
Phase 3: swap implementation for Ultralytics (x86/CI) + isaac_ros_yolov8 (Jetson)
behind the SWARM_YOLO_BACKEND env var. See ADR 0006.
"""

import os

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray


BACKEND_ENV = "SWARM_YOLO_BACKEND"
BACKEND_PASSTHROUGH = "passthrough"
BACKEND_ULTRALYTICS = "ultralytics"
BACKEND_ISAAC_ROS = "isaac_ros"


class YoloDetectorNode(Node):
    def __init__(self) -> None:
        super().__init__("yolo_detector")
        self.backend = os.environ.get(BACKEND_ENV, BACKEND_PASSTHROUGH)
        self.get_logger().info(f"Backend: {self.backend}")
        self.image_sub = self.create_subscription(
            Image, "camera/image_raw", self._on_image, 10
        )
        self.det_pub = self.create_publisher(
            Detection2DArray, "perception/detections_raw", 10
        )

    def _on_image(self, msg: Image) -> None:
        if self.backend == BACKEND_PASSTHROUGH:
            out = Detection2DArray()
            out.header = msg.header
            self.det_pub.publish(out)
            return
        # Real backends land in Phase 3.
        raise NotImplementedError(f"Backend {self.backend} not implemented yet")


def main() -> None:
    rclpy.init()
    node = YoloDetectorNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
