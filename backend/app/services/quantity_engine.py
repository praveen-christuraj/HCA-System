"""Operation Entry quantity engine (exact port of the OTMS formulas).

The OTMS entry layouts compute every quantity live in the browser
(``frontend/src/utils/tankQuantityEngine.js`` and the per-layout engines). HCA
keeps the same formulas and rounding so historical numbers reconcile, but the
engine lives here, on the server, so the API is the single source of truth
(ADR-017): the live cards on the Operation Entry page call
``POST /api/operation-entries/calculate`` and the saved payload always carries
values this engine produced — never a client-trusted copy.

Formula chain (tank gauging, tanker and every calibrated layout):

    TOV, Free Water  ← calibration interpolation of dip / water level
    GOV              = TOV − Free Water
    API@60           ← observed API or observed density + sample temperature
    VCF              ← API@60 + tank temperature
    GSV              = GOV × VCF
    BS&W volume      = GSV × BS&W%
    NSV              = GSV − BS&W volume
    LT               = NSV × LT factor (Table 11 at API@60)
    MT               = LT × 1.01605

Interpolation goes through ``app.services.calibration_engine`` so entry
quantities and the Asset Calibration calculator can never disagree.
"""

from __future__ import annotations

import math
from typing import Sequence

from app.services.calibration_engine import (
    CalibrationError,
    CalibrationPoint,
    interpolate_2d,
)
from app.services.table11 import lookup_table11_factor
from app.utils.operation_entry_payloads import (
    BARREL_TO_CUBIC_METER,
    BSW_LIMITS,
    LONG_TON_TO_METRIC_TON,
    OBSERVED_API,
    OBSERVED_API_LIMITS,
    OBSERVED_DENSITY_LIMITS,
    OBSERVED_DENSITY,
    SAMPLE_TEMP_LIMITS,
    TANK_TEMP_LIMITS,
    WATER_DENSITY_AT_60F,
)

MASS_METHOD_APPROX = "Approximate density conversion"
MASS_METHOD_APPROX_NO_TABLE11 = "Approximate density conversion - Table 11 unavailable"
MASS_METHOD_TABLE11 = "Table 11 factor lookup"


# ---------------------------------------------------------------------------
# Small numeric helpers (OTMS parseNumber / clampNumber / roundTo)
# ---------------------------------------------------------------------------
def parse_number(value, fallback=None):
    if value is None or value == "":
        return fallback
    if isinstance(value, bool):
        return fallback
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(number):  # Reject NaN and both infinities
        return fallback
    return number


def round_to(value, decimals: int = 3) -> float:
    """OTMS ``roundTo``: JavaScript ``Math.round`` semantics (half toward +∞)."""
    number = parse_number(value, 0.0)
    factor = 10**decimals
    return math.floor(number * factor + 0.5) / factor


def js_round(value) -> int:
    """OTMS ``Math.round`` on a whole number of units (bbl, tons)."""
    return int(math.floor(parse_number(value, 0.0) + 0.5))


def clamp_number(value, minimum: float, maximum: float) -> float:
    number = parse_number(value, minimum)
    if number < minimum:
        return minimum
    if number > maximum:
        return maximum
    return number


def normalize_temperature_unit(unit) -> str:
    value = str(unit or "").replace("°", "").strip().upper()
    return "F" if value == "F" else "C"


def celsius_to_fahrenheit(value) -> float:
    return parse_number(value, 0.0) * 1.8 + 32.0


def fahrenheit_to_celsius(value) -> float:
    return (parse_number(value, 0.0) - 32.0) / 1.8


def temperature_limits(unit, kind: str = "tank") -> dict:
    table = SAMPLE_TEMP_LIMITS if kind == "sample" else TANK_TEMP_LIMITS
    return table[normalize_temperature_unit(unit)]


# ---------------------------------------------------------------------------
# Density / API conversions (OTMS tankQuantityEngine)
# ---------------------------------------------------------------------------
def density_from_api(api) -> float:
    api_value = parse_number(api, 0.0)
    if api_value <= 0:
        return 0.0
    specific_gravity = 141.5 / (api_value + 131.5)
    return round_to(specific_gravity * WATER_DENSITY_AT_60F, 1)


def api_from_density(density) -> float:
    density_value = parse_number(density, 0.0)
    if density_value <= 0:
        return 0.0
    specific_gravity = density_value / WATER_DENSITY_AT_60F
    if specific_gravity <= 0:
        return 0.0
    return round_to(141.5 / specific_gravity - 131.5, 2)


def api_observed_to_api60(api_observed, sample_temperature_f, decimals=3) -> float:
    api_value = parse_number(api_observed, 0.0)
    temperature_f = parse_number(sample_temperature_f, 60.0)
    if api_value <= 0:
        return 0.0

    temperature_difference = temperature_f - 60.0
    observed_density = (
        (141.5 * WATER_DENSITY_AT_60F) / (131.5 + api_value)
    ) * (
        (1 - 0.00001278 * temperature_difference)
        - 0.0000000062 * temperature_difference * temperature_difference
    )

    corrected_density = observed_density
    for _ in range(10):
        alpha = 341.0957 / (corrected_density * corrected_density)
        vcf = math.exp(
            -alpha * temperature_difference
            - 0.8 * alpha * alpha * temperature_difference * temperature_difference
        )
        corrected_density = observed_density / vcf

    return round_to((141.5 * WATER_DENSITY_AT_60F) / corrected_density - 131.5, decimals)


def density_observed_to_api60(density_observed, sample_temperature_c, decimals=3) -> dict:
    density_value = parse_number(density_observed, 0.0)
    temperature_c = parse_number(sample_temperature_c, 15.0)
    if density_value <= 0:
        return {"api60": 0.0, "density15": 0.0}

    temperature_difference = temperature_c - 15.0
    hydrocarbon_correction = (
        (1 - 0.00001278 * temperature_difference)
        - 0.0000000062 * temperature_difference * temperature_difference
    )
    corrected_observed_density = density_value * hydrocarbon_correction

    density15 = corrected_observed_density
    for _ in range(17):
        coefficient = 613.9723 / (density15 * density15)
        vcf = math.exp(
            -coefficient
            * temperature_difference
            * (1 + 0.8 * coefficient * temperature_difference)
        )
        density15 = corrected_observed_density / vcf

    specific_gravity_60 = density15 / WATER_DENSITY_AT_60F
    api60 = 141.5 / specific_gravity_60 - 131.5 if specific_gravity_60 > 0 else 0.0
    return {"api60": round_to(api60, decimals), "density15": round_to(density15, 3)}


def get_api60_from_observed_input(
    *,
    observed_input_type,
    observed_api=None,
    observed_density=None,
    sample_temperature=None,
    sample_temperature_unit="F",
) -> dict:
    sample_unit = normalize_temperature_unit(sample_temperature_unit)

    if "api" in str(observed_input_type or OBSERVED_API).lower():
        sample_temperature_f = (
            parse_number(sample_temperature, 60.0)
            if sample_unit == "F"
            else celsius_to_fahrenheit(sample_temperature)
        )
        api60 = api_observed_to_api60(observed_api, sample_temperature_f)
        return {
            "api60": api60,
            "density15": 0.0,
            "observed_api": parse_number(observed_api, 0.0),
            "observed_density": density_from_api(observed_api),
        }

    sample_temperature_c = (
        parse_number(sample_temperature, 15.0)
        if sample_unit == "C"
        else fahrenheit_to_celsius(sample_temperature)
    )
    density_result = density_observed_to_api60(observed_density, sample_temperature_c)
    return {
        "api60": density_result["api60"],
        "density15": density_result["density15"],
        "observed_api": api_from_density(observed_density),
        "observed_density": parse_number(observed_density, 0.0),
    }


def calculate_vcf(api60, tank_temperature_f) -> float:
    api_value = parse_number(api60, 0.0)
    temperature_f = parse_number(tank_temperature_f, 60.0)
    if api_value <= 0:
        return 0.0

    temperature_difference = temperature_f - 60.0
    density60 = (141.5 * WATER_DENSITY_AT_60F) / (api_value + 131.5)
    alpha = 341.0957 / (density60 * density60)
    return round_to(
        math.exp(
            -alpha * temperature_difference
            - 0.8 * alpha * alpha * temperature_difference * temperature_difference
        ),
        5,
    )


def calculate_vcf_from_api60_and_tank_temperature(
    *, api60, tank_temperature, tank_temperature_unit="C"
) -> float:
    tank_unit = normalize_temperature_unit(tank_temperature_unit)
    tank_temperature_f = (
        parse_number(tank_temperature, 60.0)
        if tank_unit == "F"
        else celsius_to_fahrenheit(tank_temperature)
    )
    return calculate_vcf(api60, tank_temperature_f)


def density15_from_api60(api60) -> float:
    api_value = parse_number(api60, 0.0)
    if api_value <= 0:
        return 0.0
    specific_gravity_60 = 141.5 / (api_value + 131.5)
    return round_to(specific_gravity_60 * WATER_DENSITY_AT_60F, 3)


# ---------------------------------------------------------------------------
# Mass
# ---------------------------------------------------------------------------
def calculate_approximate_mass_from_nsv(*, nsv_bbl, api60=None, density15=None) -> dict:
    safe_nsv = parse_number(nsv_bbl, 0.0)
    if safe_nsv <= 0:
        return {"lt": 0, "mt": 0, "mass_method": MASS_METHOD_APPROX}

    working_density15 = parse_number(density15, 0.0)
    if working_density15 <= 0:
        working_density15 = density15_from_api60(api60)
    if working_density15 <= 0:
        return {"lt": 0, "mt": 0, "mass_method": "Mass not calculated - API/Density missing"}

    volume_m3 = safe_nsv * BARREL_TO_CUBIC_METER
    metric_ton = volume_m3 * (working_density15 / 1000.0)
    long_ton = metric_ton / LONG_TON_TO_METRIC_TON
    return {
        "lt": js_round(long_ton),
        "mt": js_round(metric_ton),
        "mass_method": MASS_METHOD_APPROX,
    }


def apply_table11_mass(*, nsv_bbl, api60, base: dict, table11_lookup: dict | None) -> dict:
    """Attach LT/MT to a calculated block, exactly like the OTMS layouts.

    Keys stay camelCase to match the OTMS payload ``calculated`` block.
    """
    result = dict(base)
    safe_nsv = parse_number(nsv_bbl, 0.0)

    if not table11_lookup or not table11_lookup.get("lt_factor"):
        approx = calculate_approximate_mass_from_nsv(
            nsv_bbl=safe_nsv,
            api60=api60,
            density15=result.get("density15"),
        )
        result["ltFactor"] = None
        result["table11LookupMethod"] = None
        result["table11LowerApi60"] = None
        result["table11UpperApi60"] = None
        result["lt"] = approx["lt"]
        result["mt"] = approx["mt"]
        result["massMethod"] = approx["mass_method"]
        return result

    lt_factor = parse_number(table11_lookup.get("lt_factor"), 0.0)
    lt = js_round(safe_nsv * lt_factor)
    mt = js_round(lt * LONG_TON_TO_METRIC_TON)
    result["ltFactor"] = lt_factor
    result["table11LookupMethod"] = table11_lookup.get("lookup_method")
    result["table11LowerApi60"] = table11_lookup.get("lower_api60")
    result["table11UpperApi60"] = table11_lookup.get("upper_api60")
    result["lt"] = lt
    result["mt"] = mt
    result["massMethod"] = MASS_METHOD_TABLE11
    return result


def lookup_mass_factor(api60, db=None) -> dict | None:
    """Table 11 lookup wrapped so a lookup failure degrades like OTMS."""
    try:
        return lookup_table11_factor(api60, db)
    except (ValueError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Calibration interpolation (OTMS linearInterpolation, via ADR-017 engine)
# ---------------------------------------------------------------------------
def interpolate_volume(points, dip_cm, *, basis="Dip", allow_clamping=False) -> dict:
    """Shared ADR-017 engine: an unresolvable quantity is never silently zero."""
    curve = [CalibrationPoint(dip_cm=float(p[0]), volume_bbl=float(p[1])) for p in points]
    target = parse_number(dip_cm, None)
    if target is None:
        raise CalibrationError("A finite dip/ullage reading is required")
    result = interpolate_2d(curve, target, basis=basis, allow_clamping=allow_clamping)
    return {"volume_bbl": result.volume_bbl, "method": result.method,
            "in_range": result.in_range, "warnings": list(result.warnings)}


# ---------------------------------------------------------------------------
# Tank gauging / tanker quantity
# ---------------------------------------------------------------------------
def calculate_tank_quantity(
    *,
    dip_cm,
    water_level_cm,
    tank_temperature,
    tank_temperature_unit,
    observed_input_type,
    observed_api=None,
    observed_density=None,
    sample_temperature=None,
    sample_temperature_unit="F",
    bsw_percent,
    calibration_points: Sequence[tuple[float, float]],
    db=None, basis="Dip",
) -> dict:
    tov_lookup = interpolate_volume(calibration_points, dip_cm, basis=basis)
    water_level = parse_number(water_level_cm, 0.0)
    free_water_lookup = (
        {"volume_bbl": 0.0, "method": "exact", "in_range": True, "warnings": []}
        if water_level <= 0
        else interpolate_volume(calibration_points, water_level, basis=basis)
    )

    tov_bbl = tov_lookup["volume_bbl"]
    free_water_bbl = free_water_lookup["volume_bbl"]
    gov_bbl = max(tov_bbl - free_water_bbl, 0.0)

    api_result = get_api60_from_observed_input(
        observed_input_type=observed_input_type,
        observed_api=observed_api,
        observed_density=observed_density,
        sample_temperature=sample_temperature,
        sample_temperature_unit=sample_temperature_unit,
    )

    vcf = calculate_vcf_from_api60_and_tank_temperature(
        api60=api_result["api60"],
        tank_temperature=tank_temperature,
        tank_temperature_unit=tank_temperature_unit,
    )

    gsv_bbl = js_round(gov_bbl * vcf)
    safe_bsw = clamp_number(bsw_percent, BSW_LIMITS["min"], BSW_LIMITS["max"])
    bsw_bbl = js_round(gsv_bbl * (safe_bsw / 100.0))
    nsv_bbl = max(js_round(gsv_bbl - bsw_bbl), 0)

    resolved_density15 = (
        api_result["density15"]
        if api_result["density15"] and api_result["density15"] > 0
        else density15_from_api60(api_result["api60"])
    )

    calculated = {
        "tovBbl": round_to(tov_bbl, 3),
        "freeWaterBbl": round_to(free_water_bbl, 3),
        "govBbl": round_to(gov_bbl, 3),
        "observedApi": round_to(api_result["observed_api"], 3),
        "observedDensity": round_to(api_result["observed_density"], 3),
        "api60": round_to(api_result["api60"], 3),
        "density15": round_to(resolved_density15, 3),
        "vcf": vcf,
        "gsvBbl": gsv_bbl,
        "bswBbl": bsw_bbl,
        "nsvBbl": nsv_bbl,
    }

    table11 = lookup_mass_factor(calculated["api60"], db)
    calculated = apply_table11_mass(
        nsv_bbl=nsv_bbl,
        api60=calculated["api60"],
        base=calculated,
        table11_lookup=table11,
    )
    return {
        "calculated": calculated,
        "interpolation": {"tov": tov_lookup, "free_water": free_water_lookup},
        "table11": table11,
    }


# ---------------------------------------------------------------------------
# Validations (OTMS validateTankGaugingInput + mandatory section checks)
# ---------------------------------------------------------------------------
def validate_quality_inputs(
    *,
    tank_temperature,
    tank_temperature_unit,
    observed_input_type,
    observed_api=None,
    observed_density=None,
    sample_temperature=None,
    sample_temperature_unit="F",
    bsw_percent,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    tank_unit = normalize_temperature_unit(tank_temperature_unit)
    tank_limits = temperature_limits(tank_unit, "tank")
    tank_temp = parse_number(tank_temperature, None)
    if tank_temp is None:
        errors.append("Tank Temperature is required.")
    elif tank_temp < tank_limits["min"] or tank_temp > tank_limits["max"]:
        errors.append(
            f"Tank Temperature must be between {tank_limits['min']} and "
            f"{tank_limits['max']} °{tank_unit}."
        )

    sample_unit = normalize_temperature_unit(sample_temperature_unit)
    sample_limits = temperature_limits(sample_unit, "sample")
    sample_temp = parse_number(sample_temperature, None)
    if sample_temp is None:
        errors.append("Sample Temperature is required.")
    elif sample_temp < sample_limits["min"] or sample_temp > sample_limits["max"]:
        errors.append(
            f"Sample Temperature must be between {sample_limits['min']} and "
            f"{sample_limits['max']} °{sample_unit}."
        )

    if "api" in str(observed_input_type or OBSERVED_API).lower():
        api = parse_number(observed_api, None)
        if api is None:
            errors.append("Observed API is required.")
        elif api < OBSERVED_API_LIMITS["min"] or api > OBSERVED_API_LIMITS["max"]:
            errors.append(
                f"Observed API must be between {OBSERVED_API_LIMITS['min']} and "
                f"{OBSERVED_API_LIMITS['max']}."
            )
    else:
        density = parse_number(observed_density, None)
        if density is None:
            errors.append("Observed Density is required.")
        elif (
            density < OBSERVED_DENSITY_LIMITS["min"]
            or density > OBSERVED_DENSITY_LIMITS["max"]
        ):
            errors.append(
                f"Observed Density must be between {OBSERVED_DENSITY_LIMITS['min']} and "
                f"{OBSERVED_DENSITY_LIMITS['max']} kg/m³."
            )

    bsw = parse_number(bsw_percent, None)
    if bsw is None:
        errors.append("BS&W % is required.")
    elif bsw < BSW_LIMITS["min"] or bsw > BSW_LIMITS["max"]:
        errors.append("BS&W % must be between 0 and 100.")

    return errors, warnings


def validate_tank_gauging_input(
    *,
    dip_cm,
    water_level_cm,
    max_calibration_dip_cm=None,
    tank_temperature,
    tank_temperature_unit,
    observed_input_type,
    observed_api=None,
    observed_density=None,
    sample_temperature=None,
    sample_temperature_unit="F",
    bsw_percent,
) -> dict:
    errors: list[str] = []
    warnings: list[str] = []

    max_dip = parse_number(max_calibration_dip_cm, 0.0) or 0.0
    dip = parse_number(dip_cm, None)
    water_level = parse_number(water_level_cm, None)

    if dip is None:
        errors.append("Dip is required.")
    elif dip < 0:
        errors.append("Dip cannot be less than 0 cm.")
    elif max_dip > 0 and dip > max_dip:
        errors.append(f"Dip cannot exceed calibration maximum {max_dip:g} cm.")

    if water_level is None:
        errors.append("Water Level is required.")
    elif water_level < 0:
        errors.append("Water Level cannot be less than 0 cm.")
    elif max_dip > 0 and water_level > max_dip:
        errors.append(f"Water Level cannot exceed calibration maximum {max_dip:g} cm.")

    if water_level is not None and dip is not None and water_level > dip:
        warnings.append("Water Level is greater than Dip. Please verify the gauging.")

    quality_errors, quality_warnings = validate_quality_inputs(
        tank_temperature=tank_temperature,
        tank_temperature_unit=tank_temperature_unit,
        observed_input_type=observed_input_type,
        observed_api=observed_api,
        observed_density=observed_density,
        sample_temperature=sample_temperature,
        sample_temperature_unit=sample_temperature_unit,
        bsw_percent=bsw_percent,
    )
    errors.extend(quality_errors)
    warnings.extend(quality_warnings)
    return {"errors": errors, "warnings": warnings}


def is_blank(value) -> bool:
    return str(value if value is not None else "").strip() == ""


def validate_tank_gauging_mandatory(inputs: dict) -> list[str]:
    missing: list[str] = []
    if is_blank(inputs.get("gaugingDate")):
        missing.append("Gauging Date")
    if is_blank(inputs.get("gaugingTime")):
        missing.append("Gauging Time")
    if is_blank(inputs.get("dipCm")):
        missing.append("Dip (cm)")
    if is_blank(inputs.get("waterLevelCm")):
        missing.append("Water Level (cm)")
    if is_blank(inputs.get("tankTemperature")):
        missing.append("Tank Temperature")
    if is_blank(inputs.get("sampleTemperature")):
        missing.append("Sample Temperature")
    if is_blank(inputs.get("bswPercent")):
        missing.append("BS&W %")

    mode = str(inputs.get("observedInputType") or "").lower()
    if "api" in mode:
        if is_blank(inputs.get("observedApi")):
            missing.append("Observed API")
    else:
        if is_blank(inputs.get("observedDensity")):
            missing.append("Observed Density")

    if is_blank(inputs.get("tankOperationCode")):
        missing.append("Tank Operation")
    return missing


def validate_tanker_mandatory(inputs: dict) -> list[str]:
    missing: list[str] = []
    if is_blank(inputs.get("tankerTransactionDate")):
        missing.append("Tanker Date")
    if is_blank(inputs.get("tankerTransactionTime")):
        missing.append("Tanker Time")
    if is_blank(inputs.get("convoyNumber")):
        missing.append("Convoy Number")
    if is_blank(inputs.get("compartment")):
        missing.append("Compartment / Manhole")
    if is_blank(inputs.get("totalDipCm")):
        missing.append("Total Dip (cm)")
    if is_blank(inputs.get("waterDipCm")):
        missing.append("Water Dip (cm)")
    if is_blank(inputs.get("bswPercent")):
        missing.append("BS&W %")
    if is_blank(inputs.get("tankTemperature")):
        missing.append("Tank Temperature")
    if is_blank(inputs.get("sampleTemperature")):
        missing.append("Sample Temperature")

    mode = str(inputs.get("observedInputType") or "").lower()
    if "api" in mode:
        if is_blank(inputs.get("observedApi")):
            missing.append("Observed API")
    else:
        if is_blank(inputs.get("observedDensity")):
            missing.append("Observed Density")
    return missing


def validate_multi_tank_mandatory(meta: dict, inputs: dict) -> list[str]:
    tank_ids = list(meta.get("tankIds") or [])
    if not tank_ids:
        return ["No tanks are declared for this asset"]

    def stage_missing(stage_name: str, stage: dict) -> list[str]:
        miss: list[str] = []
        if is_blank(stage.get("tankTemp")):
            miss.append(f"{stage_name}: Tank Temp")
        if is_blank(stage.get("sampleTemp")):
            miss.append(f"{stage_name}: Sample Temp")
        if is_blank(stage.get("bswPct")):
            miss.append(f"{stage_name}: BS&W %")

        mode = str(stage.get("obsMode") or "").lower()
        if "api" in mode:
            if is_blank(stage.get("obsApi")):
                miss.append(f"{stage_name}: Observed API")
        else:
            if is_blank(stage.get("obsDensity")):
                miss.append(f"{stage_name}: Observed Density")

        for tank_id in tank_ids:
            dip = (stage.get("dips") or {}).get(tank_id) or {}
            if is_blank(dip.get("total")):
                miss.append(f"{stage_name}: {tank_id} Total Dip")
            if is_blank(dip.get("water")):
                miss.append(f"{stage_name}: {tank_id} Water Dip")
        return miss

    missing = stage_missing("Before", inputs.get("before") or {})
    missing.extend(stage_missing("After", inputs.get("after") or {}))
    return missing


def validate_flowmeter_inputs(inputs: dict) -> list[str]:
    errors: list[str] = []
    meters = list(inputs.get("meters") or [])
    tank_temp = parse_number(inputs.get("tank_temperature"), None)
    sample_temp = parse_number(inputs.get("sample_temperature"), None)
    bsw = parse_number(inputs.get("bsw_percent"), None)
    observed_type = str(inputs.get("observed_input_type") or "")
    observed_api = parse_number(inputs.get("observed_api"), None)
    observed_density = parse_number(inputs.get("observed_density"), None)

    if is_blank(inputs.get("reading_date")):
        errors.append("Flowmeter Date is required.")
    if meters:
        if is_blank(inputs.get("stream_name")):
            errors.append("Flowmeter Stream is required.")
        for meter in meters:
            opening = parse_number(meter.get("opening_reading"), None)
            closing = parse_number(meter.get("closing_reading"), None)
            label = str(meter.get("meter_label") or "Meter")
            if opening is None or opening < 0:
                errors.append(f"{label}: Opening Reading cannot be negative.")
                continue
            if closing is None or closing < 0:
                errors.append(f"{label}: Closing Reading cannot be negative.")
                continue
            if closing < opening:
                errors.append(f"{label}: Closing Reading cannot be less than Opening Reading.")
    elif is_blank(inputs.get("meter_label")):
        errors.append("Flowmeter Meter Label is required.")

    if tank_temp is None:
        errors.append("Tank Temperature is required.")
    if sample_temp is None:
        errors.append("Sample Temperature is required.")
    if bsw is None or bsw < BSW_LIMITS["min"] or bsw > BSW_LIMITS["max"]:
        errors.append("BS & W must be between 0 and 100.")

    if observed_type == OBSERVED_API:
        if observed_api is None:
            errors.append("Observed API is required.")
    elif observed_type == OBSERVED_DENSITY:
        if observed_density is None:
            errors.append("Observed Density is required.")
    else:
        errors.append("Observed Input Type is required.")
    return errors


# ---------------------------------------------------------------------------
# Multi-tank before/after (barge) quantity
# ---------------------------------------------------------------------------
def compute_stage_totals(*, stage, tank_ids, tank_curves, db=None, basis="Dip") -> dict:
    """Port of MultiTankBeforeAfterLayout.computeStage, including CCF and API 2dp."""
    per_tank = {}
    ccf = parse_number(stage.get("ccf"), 1.0) or 1.0
    total_tov = total_fw = 0.0
    for tid in tank_ids:
        dip = (stage.get("dips") or {}).get(tid) or {}
        total = parse_number(dip.get("total"), 0.0)
        water = parse_number(dip.get("water"), 0.0)
        tov = interpolate_volume(tank_curves[tid], total, basis=basis)["volume_bbl"] * ccf
        fw = (interpolate_volume(tank_curves[tid], water, basis=basis)["volume_bbl"] if water > 0 else 0.0) * ccf
        total_tov += tov
        total_fw += fw
        per_tank[tid] = {"totalDip": total, "waterDip": water,
                         "tovCorrected": round_to(tov, 2), "fwCorrected": round_to(fw, 2)}
    if "api" in str(stage.get("obsMode", "Observed API")).lower():
        temp = parse_number(stage.get("sampleTemp"), 60.0)
        if normalize_temperature_unit(stage.get("sampleTempUnit")) != "F":
            temp = celsius_to_fahrenheit(temp)
        api60 = api_observed_to_api60(stage.get("obsApi"), temp, decimals=2)
    else:
        temp = parse_number(stage.get("sampleTemp"), 15.0)
        if normalize_temperature_unit(stage.get("sampleTempUnit")) == "F":
            temp = fahrenheit_to_celsius(temp)
        api60 = density_observed_to_api60(stage.get("obsDensity"), temp, decimals=2)["api60"]
    vcf = calculate_vcf_from_api60_and_tank_temperature(api60=api60,
        tank_temperature=stage.get("tankTemp"), tank_temperature_unit=stage.get("tankTempUnit"))
    gov = total_tov - total_fw  # OTMS deliberately keeps signed before/after quantities.
    gsv = js_round(gov * vcf)
    bsw = js_round(gsv * parse_number(stage.get("bswPct"), 0) / 100)
    nsv = js_round(gsv - bsw)
    table11 = lookup_mass_factor(api60, db)
    factor = (table11 or {}).get("lt_factor", 0)
    lt = js_round(nsv * factor)
    totals = {"TOV": round_to(total_tov, 2), "FW": round_to(total_fw, 2), "GOV": round_to(gov, 2),
              "API60": api60, "VCF": vcf, "GSV": gsv, "BSW": bsw, "NSV": nsv,
              "ltFactor": factor, "LT": lt, "MT": js_round(lt * LONG_TON_TO_METRIC_TON),
              "table11Method": (table11 or {}).get("lookup_method", ""), "table11": ({"api60": table11["api60"],
              "ltFactor": table11["lt_factor"], "lowerApi60": table11["lower_api60"], "upperApi60": table11["upper_api60"],
              "lookupMethod": table11["lookup_method"]} if table11 else None)}
    return {"perTank": per_tank, "totals": totals, "table11": table11}


def compute_multi_tank_net(before_totals: dict, after_totals: dict) -> dict:
    """OTMS ``netTotals``: After − Before on every total."""
    keys = ("TOV", "FW", "GOV", "GSV", "BSW", "NSV", "LT", "MT")
    net = {}
    for key in keys:
        value = parse_number(after_totals.get(key), 0.0) - parse_number(
            before_totals.get(key), 0.0
        )
        net[key] = round_to(value, 2) if key in ("TOV", "FW", "GOV") else js_round(value)
    return net


# ---------------------------------------------------------------------------
# Shuttle / FSO nets (OTMS shuttle_payload_v2 / fso_payload_v2)
# ---------------------------------------------------------------------------
def calculate_shuttle_net(
    *, opening_stock_bbl, opening_water_bbl, closing_stock_bbl, closing_water_bbl
) -> dict:
    opening_stock = parse_number(opening_stock_bbl, 0.0)
    opening_water = parse_number(opening_water_bbl, 0.0)
    closing_stock = parse_number(closing_stock_bbl, 0.0)
    closing_water = parse_number(closing_water_bbl, 0.0)
    net_stock = closing_stock - opening_stock
    net_water = closing_water - opening_water
    return {
        "net": {
            "net_stock_bbl": net_stock,
            "net_water_bbl": net_water,
            # Compatibility keys for movement mapping / totals (OTMS):
            "TOV": net_stock,
            "FW": net_water,
            "NSV": net_stock,
        }
    }


def calculate_fso_net(
    *,
    opening_stock_bbl,
    opening_water_bbl,
    closing_stock_bbl,
    closing_water_bbl,
    vessel_quantity_bbl,
) -> dict:
    opening_stock = parse_number(opening_stock_bbl, 0.0)
    opening_water = parse_number(opening_water_bbl, 0.0)
    closing_stock = parse_number(closing_stock_bbl, 0.0)
    closing_water = parse_number(closing_water_bbl, 0.0)
    vessel_qty = parse_number(vessel_quantity_bbl, 0.0)
    net_stock = closing_stock - opening_stock
    net_water = closing_water - opening_water
    variance = vessel_qty - abs(net_stock + net_water)
    return {
        "net": {
            "net_stock_bbl": net_stock,
            "net_water_bbl": net_water,
            "variance_bbl": variance,
        }
    }


# ---------------------------------------------------------------------------
# Flowmeter reading quantity (OTMS flowmeter_payload_v2)
# ---------------------------------------------------------------------------
M3_TO_BBLS_FACTOR = 6.289811


def calculate_flowmeter_quantities(inputs: dict) -> dict:
    meters = list(inputs.get("meters") or [])
    meter_results = []
    stream_gross_observed = 0.0
    stream_gross_observed_bbl = 0.0

    for meter in meters:
        meter_factor = parse_number(meter.get("meter_factor"), 1.0) or 1.0
        meter_unit = str(meter.get("meter_unit") or "m3").strip().lower()
        opening = parse_number(meter.get("opening_reading"), 0.0)
        closing = parse_number(meter.get("closing_reading"), 0.0)
        gross_observed = (closing - opening) * meter_factor
        if meter_unit in ("bbl", "bbls", "barrel", "barrels"):
            gross_observed_bbl = gross_observed
        elif meter_unit in ("l", "ltr", "litre", "litres", "liter", "liters"):
            gross_observed_bbl = gross_observed / 158.987294928
        else:  # m3 (OTMS default conversion)
            gross_observed_bbl = gross_observed * M3_TO_BBLS_FACTOR

        stream_gross_observed += gross_observed
        stream_gross_observed_bbl += gross_observed_bbl
        meter_results.append(
            {
                **{key: meter.get(key) for key in (
                    "config_id", "meter_asset_code", "meter_asset_name",
                    "meter_label",
                    "opening_reading",
                    "closing_reading",
                    "meter_factor",
                    "meter_unit",
                )},
                "delta": closing - opening,
                "gross_observed": gross_observed,
                "gross_observed_bbl": gross_observed_bbl,
            }
        )

    api_result = get_api60_from_observed_input(
        observed_input_type=inputs.get("observed_input_type"),
        observed_api=inputs.get("observed_api"),
        observed_density=inputs.get("observed_density"),
        sample_temperature=inputs.get("sample_temperature"),
        sample_temperature_unit=inputs.get("sample_temperature_unit"),
    )
    vcf = calculate_vcf_from_api60_and_tank_temperature(
        api60=api_result["api60"],
        tank_temperature=inputs.get("tank_temperature"),
        tank_temperature_unit=inputs.get("tank_temperature_unit"),
    )
    bsw_percent = parse_number(inputs.get("bsw_percent"), 0.0)
    gsv_bbl = stream_gross_observed_bbl * vcf
    bsw_bbl = gsv_bbl * (bsw_percent / 100.0)
    nsv_bbl = gsv_bbl - bsw_bbl

    return {
        "meters": meter_results,
        "calculated": {
            "stream_gross_observed": stream_gross_observed,
            "stream_gross_observed_bbl": stream_gross_observed_bbl,
            "gross_observed_bbl": stream_gross_observed_bbl,
            "api60": api_result["api60"],
            "vcf": vcf,
            "gsv_bbl": gsv_bbl,
            "bsw_bbl": bsw_bbl,
            "nsv_bbl": nsv_bbl,
        },
    }
