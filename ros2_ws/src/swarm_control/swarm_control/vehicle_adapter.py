"""Vehicle adapter contract for the swarm control layer.

Ported verbatim from v1 (PLAN section F). ``VehicleAdapter`` is the
backend-neutral interface every swarm operation goes through; no MAVLink or
flight-stack concept may leak above it (ADR 0002). The MAVROS implementation
lives in ``mavros_adapter.py``; an ``AP_DDS`` sibling can be added later
without touching any caller.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .swarm_api import (
    FollowReferenceRequest,
    LandRequest,
    MotionTarget,
    PlatformProfile,
    TakeoffRequest,
)


class VehicleAdapter(ABC):
    """Backend-neutral control interface used by swarm logic."""

    @property
    @abstractmethod
    def vehicle_id(self) -> str:
        """Unique vehicle identifier."""

    @property
    @abstractmethod
    def platform_profile(self) -> PlatformProfile:
        """Underlying platform implementation."""

    @abstractmethod
    def arm(self) -> bool:
        """Arm the vehicle."""

    @abstractmethod
    def enable_external_control(self) -> bool:
        """Enable offboard / guided control."""

    @abstractmethod
    def takeoff(self, request: TakeoffRequest) -> bool:
        """Take off to the requested altitude."""

    @abstractmethod
    def go_to(self, target: MotionTarget) -> bool:
        """Fly to a target point."""

    @abstractmethod
    def hold_reference(self, request: FollowReferenceRequest) -> bool:
        """Track a moving reference frame."""

    @abstractmethod
    def cancel_motion(self) -> bool:
        """Stop any active motion behavior (go-to, follow-reference).

        Used to release a vehicle from formation tracking before issuing a
        manual waypoint, and to clear a manual waypoint before rejoining the
        formation. Best-effort: returns True if no motion is active.
        """

    @abstractmethod
    def land(self, request: LandRequest) -> bool:
        """Land the vehicle."""

    @abstractmethod
    def close(self) -> None:
        """Release resources."""
