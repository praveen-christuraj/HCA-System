"""Calibration interpolation engine.

Two dimensions of interpolation, as agreed with the owner:

* **2D** — within one tank, volume is a piecewise-linear function of the dip
  (or ullage) reading. This is the ordinary strapping-table lookup.
* **3D** — for a multi-tank asset (a barge, FSO or tanker trailer) the tank
  name is the third axis. The engine resolves the exact tank first and then
  runs the 2D interpolation on that tank's curve. A tank name is never
  approximated: an unknown tank is an error, not a nearest match, because
  returning another compartment's volume would be a custody error.

Everything is computed in canonical units (cm and bbl). Callers convert.

Compared with the OTMS implementation this engine reports *how* a value was
derived. OTMS's ``linearInterpolation`` silently clamped any reading outside
the chart to the first or last row and returned ``0`` for an empty or
unparseable table, so a dip above the certified range produced a plausible
volume with no signal that it was out of range. Here every result carries a
``method`` (``exact``, ``interpolated``, ``clamped_low``, ``clamped_high``) and
the bracketing points, and an out-of-range reading is flagged rather than
quietly absorbed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

# Rounding policy: calibration volumes are kept to 4 decimal places in bbl
# (0.0001 bbl is about 16 mL) and depths to 4 decimal places in cm.
VOLUME_DECIMALS = 4
DIP_DECIMALS = 4

METHOD_EXACT = "exact"
METHOD_INTERPOLATED = "interpolated"
METHOD_CLAMPED_LOW = "clamped_low"
METHOD_CLAMPED_HIGH = "clamped_high"

# A reading further than this outside the certified range is refused rather
# than clamped: the chart says nothing about it.
MAX_EXTRAPOLATION_CM = 5.0


@dataclass(frozen=True)
class CalibrationPoint:
    """One dip/volume pair of one tank, in canonical cm and bbl."""

    dip_cm: float
    volume_bbl: float


@dataclass(frozen=True)
class InterpolationResult:
    """A resolved volume plus everything needed to defend the number."""

    requested_dip_cm: float
    volume_bbl: float
    method: str
    in_range: bool
    lower_point: CalibrationPoint | None = None
    upper_point: CalibrationPoint | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self, *, dip_unit: str | None = None, volume_unit: str | None = None) -> dict:
        from app.utils.units import from_canonical_dip, from_canonical_volume

        payload: dict = {
            "requested_dip_cm": round(self.requested_dip_cm, DIP_DECIMALS),
            "volume_bbl": round(self.volume_bbl, VOLUME_DECIMALS),
            "method": self.method,
            "in_range": self.in_range,
            "warnings": list(self.warnings),
            "lower_point": _point_dict(self.lower_point),
            "upper_point": _point_dict(self.upper_point),
        }
        if dip_unit:
            payload["requested_dip_display"] = round(
                from_canonical_dip(self.requested_dip_cm, dip_unit), DIP_DECIMALS
            )
            payload["dip_unit"] = dip_unit
        if volume_unit:
            payload["volume_display"] = round(
                from_canonical_volume(self.volume_bbl, volume_unit), VOLUME_DECIMALS
            )
            payload["volume_unit"] = volume_unit
        return payload


def _point_dict(point: CalibrationPoint | None) -> dict | None:
    if point is None:
        return None
    return {
        "dip_cm": round(point.dip_cm, DIP_DECIMALS),
        "volume_bbl": round(point.volume_bbl, VOLUME_DECIMALS),
    }


class CalibrationError(ValueError):
    """Raised when a chart or a lookup cannot be honoured."""


def normalise_curve(points: Sequence[CalibrationPoint]) -> list[CalibrationPoint]:
    """Sort a tank's points by ascending dip and merge duplicate depths.

    A duplicated depth with two different volumes is ambiguous and rejected:
    the engine will not pick one silently.
    """
    cleaned: list[CalibrationPoint] = []
    for point in points:
        dip = round(float(point.dip_cm), DIP_DECIMALS)
        volume = round(float(point.volume_bbl), VOLUME_DECIMALS)
        cleaned.append(CalibrationPoint(dip_cm=dip, volume_bbl=volume))
    cleaned.sort(key=lambda item: item.dip_cm)

    merged: list[CalibrationPoint] = []
    for point in cleaned:
        if merged and merged[-1].dip_cm == point.dip_cm:
            if abs(merged[-1].volume_bbl - point.volume_bbl) > 1e-9:
                raise CalibrationError(
                    f"Depth {point.dip_cm:g} cm appears twice with different volumes "
                    f"({merged[-1].volume_bbl:g} and {point.volume_bbl:g} bbl)"
                )
            continue
        merged.append(point)
    return merged


def interpolate_2d(
    curve: Sequence[CalibrationPoint],
    dip_cm: float,
    *,
    basis: str = "Dip",
    allow_clamping: bool = True,
) -> InterpolationResult:
    """Piecewise-linear dip -> volume inside one tank (2D interpolation).

    ``allow_clamping=False`` refuses readings outside the certified range
    instead of holding the end volume, which is the right default for custody
    transfer.
    """
    if not curve:
        raise CalibrationError("The calibration chart has no rows for this tank")

    points = list(curve)
    if any(points[index].dip_cm > points[index + 1].dip_cm for index in range(len(points) - 1)):
        points = normalise_curve(points)

    target = round(float(dip_cm), DIP_DECIMALS)
    first, last = points[0], points[-1]

    if target < first.dip_cm:
        gap = first.dip_cm - target
        if not allow_clamping or gap > MAX_EXTRAPOLATION_CM:
            raise CalibrationError(
                f"{basis} {target:g} cm is below the certified range of this chart "
                f"(minimum {first.dip_cm:g} cm)"
            )
        return InterpolationResult(
            requested_dip_cm=target,
            volume_bbl=first.volume_bbl,
            method=METHOD_CLAMPED_LOW,
            in_range=False,
            lower_point=None,
            upper_point=first,
            warnings=(
                f"{basis} is {gap:g} cm below the chart minimum; the lowest certified "
                f"volume was used.",
            ),
        )

    if target > last.dip_cm:
        gap = target - last.dip_cm
        if not allow_clamping or gap > MAX_EXTRAPOLATION_CM:
            raise CalibrationError(
                f"{basis} {target:g} cm is above the certified range of this chart "
                f"(maximum {last.dip_cm:g} cm)"
            )
        return InterpolationResult(
            requested_dip_cm=target,
            volume_bbl=last.volume_bbl,
            method=METHOD_CLAMPED_HIGH,
            in_range=False,
            lower_point=last,
            upper_point=None,
            warnings=(
                f"{basis} is {gap:g} cm above the chart maximum; the highest certified "
                f"volume was used.",
            ),
        )

    for index in range(len(points) - 1):
        lower = points[index]
        upper = points[index + 1]
        if lower.dip_cm <= target <= upper.dip_cm:
            span = upper.dip_cm - lower.dip_cm
            if span <= 0:
                return InterpolationResult(
                    requested_dip_cm=target,
                    volume_bbl=lower.volume_bbl,
                    method=METHOD_EXACT,
                    in_range=True,
                    lower_point=lower,
                    upper_point=upper,
                )
            if target == lower.dip_cm:
                method = METHOD_EXACT
                volume = lower.volume_bbl
            elif target == upper.dip_cm:
                method = METHOD_EXACT
                volume = upper.volume_bbl
            else:
                method = METHOD_INTERPOLATED
                ratio = (target - lower.dip_cm) / span
                volume = lower.volume_bbl + ratio * (upper.volume_bbl - lower.volume_bbl)
            return InterpolationResult(
                requested_dip_cm=target,
                volume_bbl=round(volume, VOLUME_DECIMALS),
                method=method,
                in_range=True,
                lower_point=lower,
                upper_point=upper,
            )

    raise CalibrationError(f"Unable to resolve {basis} {target:g} cm against this chart")


def interpolate_3d(
    curves: dict[str, Sequence[CalibrationPoint]],
    tank_name: str,
    dip_cm: float,
    *,
    basis: str = "Dip",
    allow_clamping: bool = True,
) -> InterpolationResult:
    """Tank name + dip -> volume (3D interpolation for multi-tank assets).

    The tank axis is resolved by exact name before any interpolation, so a
    barge's ``2P`` can never return the volume of ``2S``.
    """
    if not curves:
        raise CalibrationError("This asset has no calibration chart")

    wanted = str(tank_name or "").strip()
    if not wanted:
        raise CalibrationError("Tank name is required")

    index = {str(name).strip().casefold(): name for name in curves}
    resolved = index.get(wanted.casefold())
    if resolved is None:
        available = ", ".join(sorted(curves)) or "none"
        raise CalibrationError(
            f"Tank '{wanted}' is not on this calibration chart. Available tanks: {available}"
        )

    return interpolate_2d(
        curves[resolved],
        dip_cm,
        basis=basis,
        allow_clamping=allow_clamping,
    )


def validate_curve_monotonic(
    curve: Sequence[CalibrationPoint],
    *,
    basis: str = "Dip",
) -> list[str]:
    """Physical sanity checks on one tank's curve. Returns warnings.

    A dip chart must not lose volume as the dip grows, and an ullage chart must
    not gain volume as the ullage grows (ullage is measured downwards from the
    reference point, so it moves the opposite way to a dip). A reversal usually
    means a transposed column or a mis-keyed row, so it is reported rather than
    trusted.
    """
    points = list(curve)
    warnings: list[str] = []
    for index in range(len(points) - 1):
        current, following = points[index], points[index + 1]
        delta = following.volume_bbl - current.volume_bbl
        if basis == "Ullage" and delta > 1e-9:
            warnings.append(
                f"Volume rises from {current.volume_bbl:g} to {following.volume_bbl:g} bbl "
                f"while ullage increases from {current.dip_cm:g} to {following.dip_cm:g} cm"
            )
        elif basis != "Ullage" and delta < -1e-9:
            warnings.append(
                f"Volume falls from {current.volume_bbl:g} to {following.volume_bbl:g} bbl "
                f"while dip increases from {current.dip_cm:g} to {following.dip_cm:g} cm"
            )
    return warnings


def curve_summary(curve: Sequence[CalibrationPoint]) -> dict:
    """Range and capacity of one tank's curve, in canonical units."""
    points = list(curve)
    if not points:
        return {"points": 0}
    depths = [point.dip_cm for point in points]
    volumes = [point.volume_bbl for point in points]
    return {
        "points": len(points),
        "min_dip_cm": round(min(depths), DIP_DECIMALS),
        "max_dip_cm": round(max(depths), DIP_DECIMALS),
        "min_volume_bbl": round(min(volumes), VOLUME_DECIMALS),
        "max_volume_bbl": round(max(volumes), VOLUME_DECIMALS),
    }
