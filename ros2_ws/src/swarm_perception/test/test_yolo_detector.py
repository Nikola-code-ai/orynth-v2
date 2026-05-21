"""Phase 0 unit tests for the passthrough YOLO detector.

Verifies the contract that swarm_perception ships a working node from day one
(fixes v1 mistake #2): the passthrough backend turns every Image into an empty,
header-preserving Detection2DArray, and unimplemented backends fail loudly.
"""

import pytest
import rclpy
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray

from swarm_perception.yolo_detector_node import (
    BACKEND_ENV,
    BACKEND_PASSTHROUGH,
    YoloDetectorNode,
)


@pytest.fixture(scope="module", autouse=True)
def ros_context():
    rclpy.init()
    yield
    rclpy.shutdown()


@pytest.fixture
def node(monkeypatch):
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    detector = YoloDetectorNode()
    yield detector
    detector.destroy_node()


def test_defaults_to_passthrough(node):
    assert node.backend == BACKEND_PASSTHROUGH


def test_passthrough_publishes_empty_detections(node):
    captured = []

    def _capture(msg):
        captured.append(msg)

    node.det_pub.publish = _capture

    image = Image()
    image.header.frame_id = "drone_1/camera"
    node._on_image(image)

    assert len(captured) == 1
    out = captured[0]
    assert isinstance(out, Detection2DArray)
    assert out.header.frame_id == "drone_1/camera"
    assert len(out.detections) == 0


def test_unimplemented_backend_raises(monkeypatch):
    monkeypatch.setenv(BACKEND_ENV, "ultralytics")
    detector = YoloDetectorNode()
    try:
        with pytest.raises(NotImplementedError):
            detector._on_image(Image())
    finally:
        detector.destroy_node()
