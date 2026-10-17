"""Fixed OTMS payloads ↔ typed tables; validation and server-authoritative calculations.

There is deliberately no template editor and no JSON/EAV persistence. Transport
keys, CCF, rounding, seal sections and the six payload contracts are OTMS's.
HCA's canonical calibration units and fail-closed interpolation are retained.
"""
from copy import deepcopy
from datetime import date, datetime, time
import math
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Asset, AssetCalibrationTable, AssetCalibrationRow, AssetTank, OperationEntry,
    OperationEntryTankGauging, OperationEntryTanker, OperationEntryMultiTank,
    OperationEntryMultiTankStage, OperationEntryMultiTankDip, OperationEntryMultiTankSeal,
    OperationEntryShuttle, OperationEntryFso, OperationEntryFlowmeter,
    OperationEntryFlowmeterMeter, OperationEntryManualMovement, OperationEntryWarning,
    FlowmeterConfig,
)
from app.services import quantity_engine as qe
from app.services.calibration_engine import CalibrationError
from app.utils.operation_entry_payloads import resolve_entry_definition, MULTI_TANK_TEMPORARY_SEAL_KEYS
from app.utils.operation_types import get_operation_type

EDITABLE_STATUSES = ("Draft", "Rejected")
QUALITY_INPUTS = {
    "tankTemperatureUnit": "tank_temperature_unit", "tankTemperature": "tank_temperature",
    "observedInputType": "observed_input_type", "observedApi": "observed_api",
    "observedDensity": "observed_density", "sampleTemperatureUnit": "sample_temperature_unit",
    "sampleTemperature": "sample_temperature", "bswPercent": "bsw_percent", "remarks": "remarks",
}
QUALITY_CALC = {
    "tovBbl": "tov_bbl", "freeWaterBbl": "free_water_bbl", "govBbl": "gov_bbl",
    "observedApi": "calc_observed_api", "observedDensity": "calc_observed_density",
    "api60": "api60", "density15": "density15", "vcf": "vcf", "gsvBbl": "gsv_bbl",
    "bswBbl": "bsw_bbl", "nsvBbl": "nsv_bbl", "ltFactor": "lt_factor", "lt": "lt", "mt": "mt",
    "massMethod": "mass_method", "table11LookupMethod": "table11_method",
    "table11LowerApi60": "table11_lower_api60", "table11UpperApi60": "table11_upper_api60",
}
STAGE_INPUTS = {"date": "stage_date", "time": "stage_time", "ccf": "ccf", "obsMode": "obs_mode",
    "obsApi": "obs_api", "obsDensity": "obs_density", "sampleTempUnit": "sample_temp_unit",
    "sampleTemp": "sample_temp", "tankTempUnit": "tank_temp_unit", "tankTemp": "tank_temp", "bswPct": "bsw_pct"}
STAGE_CALC = {"TOV": "tov_bbl", "FW": "free_water_bbl", "GOV": "gov_bbl", "API60": "api60",
    "VCF": "vcf", "GSV": "gsv_bbl", "BSW": "bsw_bbl", "NSV": "nsv_bbl", "ltFactor": "lt_factor",
    "LT": "lt", "MT": "mt", "table11Method": "table11_method"}
TANK_INPUTS = {**QUALITY_INPUTS, "gaugingDate": "gauging_date", "gaugingTime": "gauging_time",
    "dipCm": "dip_cm", "waterLevelCm": "water_level_cm"}
TANKER_INPUTS = {**QUALITY_INPUTS, "operation": "operation_text", "tankerTransactionDate": "tanker_transaction_date",
    "tankerTransactionTime": "tanker_transaction_time", "tankerName": "tanker_name",
    "primeMoverNumber": "prime_mover_number", "chassisNumber": "chassis_number", "compartment": "compartment",
    "totalDipCm": "total_dip_cm", "waterDipCm": "water_dip_cm", "sealC1": "seal_c1", "sealC2": "seal_c2",
    "sealM1": "seal_m1", "sealM2": "seal_m2"}
STOCK_INPUTS = ["event_time", "opening_stock_bbl", "opening_water_bbl", "closing_stock_bbl", "closing_water_bbl", "remarks"]
FLOW_INPUTS = ["stream_name", "reading_date", "event_time", "tank_temperature_unit", "tank_temperature",
    "observed_input_type", "observed_api", "observed_density", "sample_temperature_unit", "sample_temperature", "bsw_percent", "remarks"]
FLOW_CALC = ["stream_gross_observed", "stream_gross_observed_bbl", "api60", "vcf", "gsv_bbl", "bsw_bbl", "nsv_bbl"]
METER_FIELDS = ["config_id", "meter_asset_code", "meter_asset_name", "meter_label", "opening_reading",
    "closing_reading", "meter_factor", "meter_unit", "gross_observed", "gross_observed_bbl"]


def generate_ticket_number(db, location_code, asset_code, operation_date):
    """OTMS location-asset-date-serial; caller locks the asset row before allocating."""
    prefix = f"{location_code.upper()}-{asset_code.upper()}-{operation_date:%Y%m%d}"
    numbers = db.query(OperationEntry.ticket_number).filter(OperationEntry.ticket_number.startswith(prefix + "-")).all()
    serials = [int(n.rsplit("-", 1)[-1]) for (n,) in numbers if n.rsplit("-", 1)[-1].isdigit()]
    return f"{prefix}-{max(serials, default=0) + 1:03d}"


def resolve_calibration_context(db, asset):
    tanks = sorted(asset.tanks, key=lambda t: (t.sort_order, t.id)) if asset else []
    table = db.query(AssetCalibrationTable).filter_by(asset_id=asset.id, status="Active").first() if asset else None
    context = {"table": table, "curves": {}, "tank_names": [t.tank_name for t in tanks], "max_dip_cm": {}, "basis": table.measurement_basis if table else "Dip"}
    if table:
        names = {t.id: t.tank_name for t in tanks}
        for row in db.query(AssetCalibrationRow).filter_by(calibration_table_id=table.id).order_by(AssetCalibrationRow.dip_cm):
            if row.tank_id in names:
                context["curves"].setdefault(names[row.tank_id], []).append((float(row.dip_cm), float(row.volume_bbl)))
        context["max_dip_cm"] = {name: max(x for x, _ in points) for name, points in context["curves"].items()}
    return context


def _check_shape(value, path="payload", depth=0):
    if depth > 8:
        raise ValueError("Payload nesting limit exceeded")
    if isinstance(value, dict):
        if len(value) > 200:
            raise ValueError(f"{path}: at most 200 fields/compartments")
        for key, item in value.items():
            if len(key) > 150:
                raise ValueError(f"{path}: field name too long")
            _check_shape(item, f"{path}.{key}", depth + 1)
    elif isinstance(value, list):
        if len(value) > 200:
            raise ValueError(f"{path}: at most 200 rows")
        for item in value:
            _check_shape(item, path, depth + 1)
    elif isinstance(value, str) and len(value) > 4000:
        raise ValueError(f"{path}: maximum 4000 characters")
    elif isinstance(value, (int, float)) and (not math.isfinite(value) or abs(value) > 1e12):
        raise ValueError(f"{path}: a finite operational value is required (absolute maximum 1e12)")


def _date_time_errors(inputs, date_key=None, time_key=None, required=False):
    errors = []
    for key, parser in ((date_key, date.fromisoformat), (time_key, time.fromisoformat)):
        if not key:
            continue
        val = inputs.get(key)
        if val in (None, ""):
            if required:
                errors.append(f"{key} is required")
        else:
            try:
                parser(str(val))
                if key == time_key and not re.fullmatch(r"\d{2}:\d{2}", str(val)):
                    raise ValueError()
            except ValueError:
                errors.append(f"{key}: use {'YYYY-MM-DD' if key == date_key else 'HH:MM'}")
    return errors


def _quality(inputs, *, stage=False, snake=False):
    names = {
        "tank_temperature": "tankTemp" if stage else "tankTemperature",
        "tank_temperature_unit": "tankTempUnit" if stage else "tankTemperatureUnit",
        "observed_input_type": "obsMode" if stage else "observedInputType",
        "observed_api": "obsApi" if stage else "observedApi",
        "observed_density": "obsDensity" if stage else "observedDensity",
        "sample_temperature": "sampleTemp" if stage else "sampleTemperature",
        "sample_temperature_unit": "sampleTempUnit" if stage else "sampleTemperatureUnit",
        "bsw_percent": "bswPct" if stage else "bswPercent",
    }
    return {key: inputs.get(key if snake else name) for key, name in names.items()}


def _quality_errors(q):
    errors, warnings = qe.validate_quality_inputs(**q)
    for key in ("tank_temperature_unit", "sample_temperature_unit"):
        if str(q.get(key) or "").replace("°", "") not in ("C", "F"):
            errors.append(f"{key} must be C or F")
    if q.get("observed_input_type") not in ("Observed API", "Observed Density", "Observed Density (kg/m³)"):
        errors.append("Observed Input Type is required")
    return errors, warnings


def _number_errors(inputs, keys, *, required=True, nonnegative=True):
    errors = []
    for key in keys:
        value = inputs.get(key)
        if value in (None, "") and not required:
            continue
        number = qe.parse_number(value, None)
        if number is None or abs(number) > 1e12:
            errors.append(f"{key}: a finite number is required")
        elif nonnegative and number < 0:
            errors.append(f"{key}: cannot be negative")
    return errors


def _select_curve(context, name):
    if not context["table"]:
        raise CalibrationError("No active calibration table. Upload a chart in Asset Calibration before saving quantities.")
    if not name or name not in context["curves"]:
        raise CalibrationError(f"Calibration has no curve for declared tank '{name or '(none)'}'; another compartment is never substituted.")
    return context["curves"][name]


def calculate_payload(db, *, operation_type_code, asset, payload, location_id=None, payload_code=None):
    definition = resolve_entry_definition(operation_type_code, payload_code)
    code = definition["payload_field_code"]
    validate_payload_shape(payload, code)
    inputs = deepcopy(payload.get("inputs") or {})
    if not isinstance(inputs, dict):
        raise ValueError("payload.inputs must be an object")
    errors, warnings, calculated = [], [], {}
    context = resolve_calibration_context(db, asset)
    extra = {}
    try:
        if code in ("tank_gauging_payload", "tanker_payload"):
            tanker = code == "tanker_payload"
            q = _quality(inputs)
            quality_errors, warnings = _quality_errors(q)
            errors.extend(quality_errors)
            dip_key, water_key = ("totalDipCm", "waterDipCm") if tanker else ("dipCm", "waterLevelCm")
            errors.extend(_number_errors(inputs, [dip_key, water_key]))
            errors.extend(_date_time_errors(inputs, "tankerTransactionDate" if tanker else "gaugingDate",
                                            "tankerTransactionTime" if tanker else "gaugingTime", required=True))
            name = inputs.get("compartment") if tanker else (context["tank_names"][0] if len(context["tank_names"]) == 1 else None)
            if not tanker and len(context["tank_names"]) != 1:
                errors.append("Tank Gauging needs exactly one declared tank; select the correct storage-tank asset.")
            curve = _select_curve(context, name)
            if not errors:
                result = qe.calculate_tank_quantity(dip_cm=inputs[dip_key], water_level_cm=inputs[water_key],
                    **q, calibration_points=curve, db=db, basis=context["basis"])
                calculated = result["calculated"]
                water, total = float(inputs[water_key]), float(inputs[dip_key])
                if context["basis"] == "Ullage" and water > 0 and water < total:
                    warnings.append("Water ullage implies more volume than total ullage. Please verify the gauging.")
                elif context["basis"] != "Ullage" and water > total:
                    warnings.append("Water Level is greater than Dip. Please verify the gauging.")
                if not result["table11"]:
                    warnings.append("Table 11 factor master is empty. Approximate density conversion is being used for mass.")
        elif code == "multi_tank_payload":
            if not context["tank_names"]:
                errors.append("No tanks are declared for this asset")
            for stage_name in ("before", "after"):
                stage = inputs.get(stage_name) or {}
                e, w = _quality_errors(_quality(stage, stage=True))
                errors.extend(f"{stage_name}: {x}" for x in e)
                warnings.extend(f"{stage_name}: {x}" for x in w)
                errors.extend(_date_time_errors(stage, "date", "time"))
                ccf = qe.parse_number(stage.get("ccf"), None)
                if ccf is None or ccf <= 0 or ccf > 10:
                    errors.append(f"{stage_name}: CCF must be greater than zero and at most 10")
                dips = stage.get("dips") or {}
                if set(dips) != set(context["tank_names"]):
                    errors.append(f"{stage_name}: dips must include every declared tank, and no unknown tank")
                for tank in context["tank_names"]:
                    d = dips.get(tank) or {}
                    errors.extend(f"{stage_name}/{tank}: {x}" for x in _number_errors(d, ["total", "water"]))
                    _select_curve(context, tank)
                    water, total = qe.parse_number(d.get("water"), 0), qe.parse_number(d.get("total"), 0)
                    if (context["basis"] == "Ullage" and water > 0 and water < total) or (context["basis"] != "Ullage" and water > total):
                        warnings.append(f"{stage_name}/{tank}: Water reading implies more volume than total reading. Verify the {context['basis']} measurements.")
            if not errors:
                stages = {k: qe.compute_stage_totals(stage=inputs[k], tank_ids=context["tank_names"],
                    tank_curves=context["curves"], db=db, basis=context["basis"]) for k in ("before", "after")}
                calculated = {k: v["totals"] for k, v in stages.items()}
                calculated["net"] = qe.compute_multi_tank_net(calculated["before"], calculated["after"])
                extra["per_tank"] = {k: v["perTank"] for k, v in stages.items()}
                if any(not s["table11"] for s in stages.values()):
                    warnings.append("Table 11 factor master is empty. Barge LT/MT are zero until reference factors are loaded (OTMS rule).")
        elif code in ("shuttle_payload", "fso_payload"):
            keys = STOCK_INPUTS[1:-1]
            errors.extend(_number_errors(inputs, keys, required=False))
            errors.extend(_date_time_errors(inputs, time_key="event_time"))
            values = {k: inputs.get(k) for k in keys}
            if code == "shuttle_payload":
                calculated = qe.calculate_shuttle_net(**values)
            else:
                errors.extend(_number_errors(inputs, ["vessel_quantity_bbl"], required=False))
                calculated = qe.calculate_fso_net(**values, vessel_quantity_bbl=inputs.get("vessel_quantity_bbl"))
        elif code == "flowmeter_payload":
            e, w = _quality_errors(_quality(inputs, snake=True))
            errors.extend(e); warnings.extend(w)
            errors.extend(_date_time_errors(inputs, "reading_date", "event_time"))
            errors.extend(qe.validate_flowmeter_inputs(inputs))
            configs = db.query(FlowmeterConfig).filter_by(asset_id=asset.id, location_id=location_id, status="Active").order_by(FlowmeterConfig.id).all()
            meters = inputs.get("meters") or []
            if not configs:
                errors.append("No active flowmeter configuration for this stream at this location.")
            try:
                ids = [int(m.get("config_id", 0)) for m in meters]
            except (TypeError, ValueError):
                ids = []
            if len(ids) != len(set(ids)) or set(ids) != {c.id for c in configs}:
                errors.append("Meter readings must match every active meter in the selected stream configuration.")
            by_id = {c.id: c for c in configs}
            canonical_meters = []
            for meter in meters:
                config = by_id.get(meter.get("config_id"))
                if not config:
                    continue
                canonical_meters.append({"config_id": config.id, "meter_asset_code": config.meter_asset.asset_code if config.meter_asset else None,
                    "meter_asset_name": config.meter_asset.asset_name if config.meter_asset else None,
                    "meter_label": config.meter_label, "meter_factor": float(config.meter_factor), "meter_unit": config.meter_unit,
                    "opening_reading": meter.get("opening_reading"), "closing_reading": meter.get("closing_reading")})
            if not errors:
                result = qe.calculate_flowmeter_quantities({**inputs, "meters": canonical_meters})
                calculated = result["calculated"]
                extra["meters"] = result["meters"]
        elif code in ("stock_movement", "vessel_cycle"):
            keys = ["opening_stock", "opening_water", "closing_stock", "closing_water"] if code == "stock_movement" else ["quantity_bbl", "water_bbl"]
            errors.extend(_number_errors(inputs, keys))
            if not errors:
                nums = {k: float(inputs[k]) for k in keys}
                if code == "stock_movement":
                    ns = nums["closing_stock"] - nums["opening_stock"]
                    nw = nums["closing_water"] - nums["opening_water"]
                    calculated = {"net_stock": ns, "net_water": nw, "net_nsv": ns - nw}
                else:
                    calculated = {"nsv_bbl": nums["quantity_bbl"] - nums["water_bbl"]}
    except (CalibrationError, ValueError, TypeError, OverflowError) as error:
        errors.append(str(error))
        calculated = {}
    return {"calculated": calculated, "validation": {"errors": list(dict.fromkeys(errors)), "warnings": warnings},
            "meta": {"tank_ids": context["tank_names"]}, **extra}


def _assign(row, values, mapping):
    """Assign only explicit columns, never mass-assign a payload."""
    from sqlalchemy import Numeric, Date
    for key, attr in mapping.items():
        value = values.get(key)
        column = row.__table__.c[attr]
        if isinstance(column.type, Numeric):
            value = qe.parse_number(value, None)
            if value is None and not column.nullable:
                value = 0
        elif isinstance(column.type, Date):
            value = date.fromisoformat(str(value)) if value else None
        elif value == "":
            value = None if column.nullable else ""
        setattr(row, attr, value)


def _output(row, mapping):
    from decimal import Decimal
    result = {}
    for key, attr in mapping.items():
        value = getattr(row, attr)
        if isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, (date, datetime)):
            value = value.isoformat()
        result[key] = value
    return result


def _identity(keys):
    return {k: k for k in keys}


def _calibration_snapshot(row, context):
    table = context["table"]
    row.calibration_table_id = table.id if table else None
    row.calibration_table_id_at_save = table.id if table else None
    row.calibration_name = table.chart_name if table else None
    row.calibration_effective_date = table.effective_date if table else None
    row.calibration_basis = context["basis"]
    row.calibration_max_dip_cm = max(context["max_dip_cm"].values(), default=0)


def persist_payload(db, entry, *, payload, result):
    code = entry.payload_code
    inputs = payload.get("inputs") or {}
    calculated = result["calculated"]
    context = resolve_calibration_context(db, entry.asset)
    for warning in list(entry.warnings):
        db.delete(warning)
    for message in result["validation"]["warnings"]:
        db.add(OperationEntryWarning(entry_id=entry.id, message=message))
    if code in ("tank_gauging_payload", "tanker_payload"):
        tanker = code == "tanker_payload"
        attr, cls, mapping = ("tanker", OperationEntryTanker, TANKER_INPUTS) if tanker else ("tank_gauging", OperationEntryTankGauging, TANK_INPUTS)
        row = getattr(entry, attr) or cls()
        setattr(entry, attr, row)
        _assign(row, inputs, mapping)
        for key in ("code", "label", "category", "sign"):
            setattr(row, "operation_" + key, getattr(entry, "operation_" + key + "_snapshot"))
        _assign(row, calculated, QUALITY_CALC)
        _calibration_snapshot(row, context)
        if tanker:
            row.calibration_max_dip_cm = context["max_dip_cm"].get(inputs.get("compartment"))
            ref = payload.get("prime_mover_asset") or {}
            row.prime_mover_name = ref.get("asset_name")
    elif code == "multi_tank_payload":
        row = entry.multi_tank or OperationEntryMultiTank()
        entry.multi_tank = row
        _calibration_snapshot(row, context)
        for key, attr in STAGE_CALC.items():
            if key in ("API60", "VCF", "ltFactor", "table11Method"):
                continue
            setattr(row, "net_" + attr, calculated["net"][key])
        # Flush deletions first to avoid duplicate stage/meter keys during replacement.
        row.stages.clear(); row.seals.clear(); db.flush()
        for name in ("before", "after"):
            stage = OperationEntryMultiTankStage(stage=name.title())
            _assign(stage, inputs[name], STAGE_INPUTS)
            _assign(stage, calculated[name], STAGE_CALC)
            table11 = calculated[name].get("table11") or {}
            stage.table11_lower_api60 = table11.get("lowerApi60")
            stage.table11_upper_api60 = table11.get("upperApi60")
            for order, tank in enumerate(context["tank_names"]):
                dip = inputs[name]["dips"][tank]
                per = result["per_tank"][name][tank]
                stage.dips.append(OperationEntryMultiTankDip(tank_name=tank, sort_order=order,
                    total_dip_cm=dip["total"], water_dip_cm=dip["water"], tov_bbl=per["tovCorrected"],
                    free_water_bbl=per["fwCorrected"], gov_bbl=per["tovCorrected"] - per["fwCorrected"]))
            row.stages.append(stage)
        after = (payload.get("seals") or {}).get("after") or {}
        for tank, cells in (after.get("tankSeals") or {}).items():
            for position, cell in cells.items():
                row.seals.append(OperationEntryMultiTankSeal(seal_group="Tank", tank_name=tank,
                    position=position, master_number=cell.get("master"), observed_number=cell.get("observed")))
        for key in MULTI_TANK_TEMPORARY_SEAL_KEYS:
            row.seals.append(OperationEntryMultiTankSeal(seal_group="Temporary", position=key,
                observed_number=str((after.get("temporary") or {}).get(key) or "")))
    elif code in ("shuttle_payload", "fso_payload"):
        fso = code == "fso_payload"
        row = (entry.fso if fso else entry.shuttle) or (OperationEntryFso() if fso else OperationEntryShuttle())
        if fso: entry.fso = row
        else: entry.shuttle = row
        extra = ["shuttle_number", "vessel_name", "vessel_quantity_bbl"] if fso else ["barge_reference"]
        _assign(row, inputs, _identity(STOCK_INPUTS + extra))
        for key in ("code", "label", "category", "sign"):
            setattr(row, "operation_" + key, getattr(entry, "operation_" + key + "_snapshot"))
        _assign(row, calculated["net"], _identity(["net_stock_bbl", "net_water_bbl"] + (["variance_bbl"] if fso else [])))
        if fso:
            row.source_shuttle_discharge_bbl = (payload.get("meta") or {}).get("source_shuttle_discharge_bbl")
            row.source_voyage_id = result.get("source_voyage_id")
    elif code == "flowmeter_payload":
        row = entry.flowmeter or OperationEntryFlowmeter()
        entry.flowmeter = row
        _assign(row, inputs, _identity(FLOW_INPUTS))
        _assign(row, calculated, _identity(FLOW_CALC))
        row.meters.clear(); db.flush()
        for index, meter in enumerate(result["meters"]):
            child = OperationEntryFlowmeterMeter(sort_order=index)
            _assign(child, meter, _identity(METER_FIELDS))
            row.meters.append(child)
    else:
        row = db.query(OperationEntryManualMovement).filter_by(entry_id=entry.id).first()
        if row is None:
            row = OperationEntryManualMovement(entry_id=entry.id); db.add(row)
        keys = [c.name for c in row.__table__.columns if c.name not in ("id", "entry_id")]
        merged = {**inputs, **calculated}
        if "nsv_bbl" in calculated:
            merged["net_nsv"] = calculated["nsv_bbl"]
        _assign(row, merged, _identity(keys))


def _asset_ref(entry):
    return {"asset_code": entry.asset_code_snapshot, "asset_name": entry.asset_name_snapshot, "asset_type_code": entry.asset_type_code}


def _calibration_ref(row, *, tanker=False):
    if not row.calibration_name:
        return None
    ref = {"calibration_table_id": row.calibration_table_id_at_save, "calibration_name": row.calibration_name,
           "template_id": 1, "template_name": "Fixed tank / dip-ullage / volume", "effective_date": row.calibration_effective_date,
           "input_column": "dip_cm", "output_column": "volume_bbl", "max_dip_cm": float(row.calibration_max_dip_cm or 0),
           "measurement_basis": row.calibration_basis}
    return ref


def payload_from_entry(entry):
    code = entry.payload_code
    asset = _asset_ref(entry)
    operation = {k: getattr(entry, "operation_" + k + "_snapshot") for k in ("code", "label", "category", "sign")}
    location = entry.location.location_code
    if code in ("tank_gauging_payload", "tanker_payload"):
        tanker = code == "tanker_payload"
        row = entry.tanker if tanker else entry.tank_gauging
        inputs = _output(row, TANKER_INPUTS if tanker else TANK_INPUTS)
        if tanker:
            inputs.update(convoyNumber=entry.convoy_number or "", cargo=entry.product_name or "")
        else:
            inputs.update({"tankOperation" + key.title(): value for key, value in operation.items()})
        payload = {"layout_type": "Tanker Loading" if tanker else "Tank Gauging",
            "calculation_engine": "Tanker Quantity" if tanker else "Tank Quantity", "asset": asset,
            "calibration": _calibration_ref(row), "inputs": inputs, "calculated": _output(row, QUALITY_CALC),
            "validation": {"errors": [], "warnings": [w.message for w in entry.warnings]}}
        if tanker:
            if payload["calibration"]: payload["calibration"]["asset_code"] = entry.asset_code_snapshot
            trailer = {**asset, "serial_number": row.chassis_number}
            pm = {"asset_code": row.prime_mover_number, "asset_name": row.prime_mover_name,
                "asset_type_code": "PRIME_MOVER", "serial_number": None} if row.prime_mover_number else None
            payload.update(prime_mover_asset=pm, tanker_trailer_asset=trailer, asset=trailer,
                sender_reference=tanker_sender_reference(entry.linked_ticket) if entry.linked_ticket else None)
        return payload
    if code == "multi_tank_payload":
        row = entry.multi_tank
        inputs, calculated, per_tank = {}, {}, {}
        tank_ids = []
        for stage in row.stages:
            name = stage.stage.lower()
            inputs[name] = _output(stage, STAGE_INPUTS)
            inputs[name]["dips"] = {d.tank_name: {"total": float(d.total_dip_cm), "water": float(d.water_dip_cm)} for d in stage.dips}
            calculated[name] = _output(stage, STAGE_CALC)
            calculated[name]["table11"] = {"api60": float(stage.api60), "ltFactor": float(stage.lt_factor),
                "lookupMethod": stage.table11_method, "lowerApi60": float(stage.table11_lower_api60),
                "upperApi60": float(stage.table11_upper_api60)} if stage.table11_lower_api60 is not None else None
            per_tank[name] = {d.tank_name: {"totalDip": float(d.total_dip_cm), "waterDip": float(d.water_dip_cm),
                "tovCorrected": float(d.tov_bbl), "fwCorrected": float(d.free_water_bbl)} for d in stage.dips}
            tank_ids = [d.tank_name for d in stage.dips]
        calculated["net"] = {key: float(getattr(row, "net_" + attr) or 0) for key, attr in STAGE_CALC.items()
            if key not in ("API60", "VCF", "ltFactor", "table11Method")}
        seals, temporary = {}, {}
        for seal in row.seals:
            if seal.seal_group == "Tank":
                seals.setdefault(seal.tank_name, {})[seal.position] = {"master": seal.master_number or "", "observed": seal.observed_number or ""}
            else:
                temporary[seal.position] = seal.observed_number or ""
        return {"meta": {"layout": "Multi-Tank Before/After", "assetCode": asset["asset_code"], "assetName": asset["asset_name"],
            "calibrationTableId": row.calibration_table_id_at_save, "templateId": 1, "referenceCol": "tank_name", "inputXCol": "dip_cm",
            "outputCol": "volume_bbl", "inputXUnit": "cm", "outputUnit": "bbl", "measurementBasis": row.calibration_basis, "tankIds": tank_ids},
            "inputs": inputs, "calculated": calculated, "perTank": per_tank, "seals": {"after": {"tankSeals": seals, "temporary": temporary}}}
    if code in ("shuttle_payload", "fso_payload"):
        fso = code == "fso_payload"
        row = entry.fso if fso else entry.shuttle
        meta = {"schema": "fso_payload_v2" if fso else "shuttle_payload_v2", "location_code": location,
            "fso_asset_code" if fso else "shuttle_asset_code": asset["asset_code"],
            "shuttle_number": row.shuttle_number if fso else entry.convoy_number}
        meta.update({("operation_" if fso else "vessel_operation_") + key: value for key, value in operation.items()})
        extra = ["shuttle_number", "vessel_name", "vessel_quantity_bbl"] if fso else ["barge_reference"]
        inputs = {**_output(row, _identity(STOCK_INPUTS + extra)), "operation_date": entry.operation_date.isoformat()}
        net = _output(row, _identity(["net_stock_bbl", "net_water_bbl"] + (["variance_bbl"] if fso else [])))
        if fso and row.source_shuttle_discharge_bbl is not None:
            meta["source_shuttle_discharge_bbl"] = float(row.source_shuttle_discharge_bbl)
        if not fso:
            net.update(TOV=net["net_stock_bbl"], FW=net["net_water_bbl"], NSV=net["net_stock_bbl"])
        return {"meta": meta, "inputs": inputs, "calculated": {"net": net}}
    if code == "flowmeter_payload":
        row = entry.flowmeter
        inputs = _output(row, _identity(FLOW_INPUTS))
        inputs.update(meter_label=row.stream_name, operation_date=entry.operation_date.isoformat())
        inputs["meters"] = [{**_output(m, _identity(METER_FIELDS)), "delta": float(m.closing_reading - m.opening_reading)} for m in row.meters]
        calculated = _output(row, _identity(FLOW_CALC))
        calculated["gross_observed_bbl"] = calculated["stream_gross_observed_bbl"]
        return {"meta": {"schema": "flowmeter_payload_v2", "location_code": location, "asset_code": asset["asset_code"], "asset_type_code": asset["asset_type_code"]},
            "inputs": inputs, "calculated": calculated}
    row = entry.manual_movement_rows[0]
    keys = ["movement_reference", "counterparty_asset_code", "quantity_bbl", "water_bbl"] if code == "vessel_cycle" else ["movement_reference", "opening_stock", "opening_water", "closing_stock", "closing_water"]
    calculated = {"nsv_bbl": float(row.net_nsv)} if code == "vessel_cycle" else _output(row, _identity(["net_stock", "net_water", "net_nsv"]))
    return {"inputs": {**_output(row, _identity(keys)), "vessel_operation_code": operation["code"]}, "calculated": calculated}


def tanker_sender_reference(sender):
    if not sender or not sender.tanker:
        return None
    r = sender.tanker
    return {"sender_transaction_id": sender.id, "ticket_number": sender.ticket_number, "operation_number": sender.ticket_number,
        "convoy_number": sender.convoy_number, "tanker_asset_code": sender.asset_code_snapshot,
        "prime_mover_asset_code": r.prime_mover_number, "sender_nsv_bbl": float(r.nsv_bbl or 0),
        "sender_gsv_bbl": float(r.gsv_bbl or 0), "sender_gov_bbl": float(r.gov_bbl or 0),
        **{f"sender_seal_{x}": getattr(r, f"seal_{x}") for x in ("c1", "c2", "m1", "m2")}}


def operation_entry_to_dict(entry, *, include_payload=True):
    definition = resolve_entry_definition(entry.operation_type_code, entry.payload_code)
    data = {c: getattr(entry, c) for c in ("id", "ticket_number", "version", "payload_code", "operation_id", "operation_type_code", "asset_type_code",
        "asset_id", "location_id", "destination_location_id", "sender_location_id", "receiver_location_id", "linked_ticket_id",
        "barge_event_type", "convoy_number", "operation_date", "operation_start_datetime", "operation_end_datetime", "product_name",
        "remarks", "status", "status_remarks", "submitted_at", "created_at", "updated_at", "created_by_user_id", "submitted_by_user_id", "approved_at", "reviewed_at")}
    data.update(operation_type_name=get_operation_type(entry.operation_type_code)["name"], entry_layout_type=definition["entry_layout_type"],
        calculation_engine=definition["calculation_engine"], payload_field_code=entry.payload_code,
        field_count=len(definition.get("fields") or [entry.payload_code]) + (1 if entry.payload_code == "multi_tank_payload" else 0), asset_code=entry.asset_code_snapshot,
        asset_name=entry.asset_name_snapshot, location_code=entry.location.location_code, location_name=entry.location.location_name,
        operation_code=entry.operation_code_snapshot, operation_category=entry.operation_category_snapshot, operation_sign=entry.operation_sign_snapshot,
        created_by=entry.created_by.username if entry.created_by else "", submitted_by=entry.submitted_by.username if entry.submitted_by else "",
        payload=payload_from_entry(entry) if include_payload else None)
    return data


def operation_entry_status_history_to_dict(row):
    return {"id": row.id, "from_status": row.from_status, "to_status": row.to_status, "action": row.action,
        "remarks": row.remarks, "actor_user_id": row.actor_user_id, "actor_name": row.actor.full_name if row.actor else "",
        "created_at": row.created_at}


def validate_payload_shape(payload, code):
    """Reject malformed/custom fields rather than dropping measurements on round-trip."""
    if not isinstance(payload, dict):
        raise ValueError("The fixed payload must be an object")
    _check_shape(payload)
    allowed_top = {"inputs", "calculated", "meta", "asset", "calibration", "validation", "layout_type", "calculation_engine"}
    if code == "multi_tank_payload": allowed_top |= {"perTank", "seals"}
    if code == "tanker_payload": allowed_top |= {"prime_mover_asset", "tanker_trailer_asset", "sender_reference"}
    if set(payload) - allowed_top:
        raise ValueError("Custom payload fields are not supported: " + ", ".join(sorted(set(payload) - allowed_top)))
    for key in allowed_top - {"layout_type", "calculation_engine"}:
        if payload.get(key) is not None and not isinstance(payload[key], dict):
            raise ValueError(f"payload.{key} must be an object")
    inputs = payload.get("inputs") or {}
    if code == "tank_gauging_payload":
        allowed = set(TANK_INPUTS) | {"tankOperationCode", "tankOperationLabel", "tankOperationCategory", "tankOperationSign"}
    elif code == "tanker_payload":
        allowed = set(TANKER_INPUTS) | {"convoyNumber", "cargo"}
    elif code == "shuttle_payload": allowed = set(STOCK_INPUTS) | {"operation_date", "barge_reference"}
    elif code == "fso_payload": allowed = set(STOCK_INPUTS) | {"operation_date", "shuttle_number", "vessel_name", "vessel_quantity_bbl"}
    elif code == "flowmeter_payload": allowed = set(FLOW_INPUTS) | {"operation_date", "meter_label", "meters"}
    elif code in ("stock_movement", "vessel_cycle"):
        from app.utils.operation_entry_payloads import MANUAL_LAYOUTS
        allowed = set(MANUAL_LAYOUTS[code]["fields"])
    else: allowed = {"before", "after"}
    if set(inputs) - allowed:
        raise ValueError("Unknown fixed input field(s): " + ", ".join(sorted(set(inputs) - allowed)))
    for key, value in inputs.items():
        if key not in ("before", "after", "meters") and isinstance(value, (dict, list, bool)):
            raise ValueError(f"{key} must be a scalar entry value")
        if isinstance(value, str):
            cap = 4000 if key == "remarks" else 150
            if len(value) > cap: raise ValueError(f"{key}: maximum {cap} characters")
    if code == "tank_gauging_payload": _validate_column_inputs(inputs, OperationEntryTankGauging, TANK_INPUTS)
    if code == "tanker_payload": _validate_column_inputs(inputs, OperationEntryTanker, TANKER_INPUTS)
    if code == "shuttle_payload": _validate_column_inputs(inputs, OperationEntryShuttle, _identity(STOCK_INPUTS + ["barge_reference"]))
    if code == "fso_payload": _validate_column_inputs(inputs, OperationEntryFso, _identity(STOCK_INPUTS + ["shuttle_number", "vessel_name", "vessel_quantity_bbl"]))
    if code == "flowmeter_payload": _validate_column_inputs(inputs, OperationEntryFlowmeter, _identity(FLOW_INPUTS))
    if code == "multi_tank_payload":
        for name in ("before", "after"):
            stage = inputs.get(name) or {}
            if not isinstance(stage, dict): raise ValueError(f"inputs.{name} must be an object")
            if set(stage) - set(STAGE_INPUTS) - {"dips"}: raise ValueError(f"Custom {name} stage fields are not supported")
            _validate_column_inputs(stage, OperationEntryMultiTankStage, STAGE_INPUTS)
            dips = stage.get("dips") or {}
            if not isinstance(dips, dict): raise ValueError(f"{name}.dips must be an object keyed by declared tank names")
            for tank, dip in dips.items():
                if not isinstance(dip, dict) or set(dip) - {"total", "water"}: raise ValueError(f"{name}/{tank}: expected total and water readings")
                _validate_column_inputs(dip, OperationEntryMultiTankDip, {"total": "total_dip_cm", "water": "water_dip_cm"})
        seals = payload.get("seals") or {}
        after = seals.get("after") or {}
        if not isinstance(after, dict): raise ValueError("seals.after must be an object")
        if not isinstance(after.get("temporary", {}), dict) or not isinstance(after.get("tankSeals", {}), dict):
            raise ValueError("Temporary and permanent seal sections must be objects")
        for cells in (after.get("tankSeals") or {}).values():
            if not isinstance(cells, dict) or any(not isinstance(cell, dict) for cell in cells.values()):
                raise ValueError("Permanent seals must map positions to master / observed cells")
            for cell in cells.values():
                if set(cell) - {"master", "observed"} or any(v is not None and not isinstance(v, str) for v in cell.values()):
                    raise ValueError("Seal master / observed values must be text")
    if code == "flowmeter_payload":
        meters = inputs.get("meters") or []
        if not isinstance(meters, list) or any(not isinstance(m, dict) for m in meters):
            raise ValueError("meters must be an array of configured meter readings")
        for m in meters:
            if set(m) - set(METER_FIELDS) - {"delta"}: raise ValueError("Unknown meter reading field")
            errors = _number_errors(m, ["opening_reading", "closing_reading"])
            if errors: raise ValueError("; ".join(errors))


def _validate_column_inputs(values, model, mapping):
    from decimal import Decimal, InvalidOperation
    from sqlalchemy import String, Numeric
    for key, attr in mapping.items():
        v = values.get(key)
        if v is None or v == "": continue
        column = model.__table__.c[attr]
        if isinstance(column.type, String):
            if not isinstance(v, str): raise ValueError(f"{key} must be text")
            if column.type.length and len(v) > column.type.length:
                raise ValueError(f"{key}: maximum {column.type.length} characters")
        if isinstance(column.type, Numeric):
            try: d = Decimal(str(v))
            except InvalidOperation: raise ValueError(f"{key}: a finite number is required")
            if not d.is_finite(): raise ValueError(f"{key}: a finite number is required")
            if abs(d) >= Decimal(10) ** (column.type.precision - column.type.scale):
                raise ValueError(f"{key}: value exceeds storage precision")
            if d != d.quantize(Decimal(10) ** -column.type.scale):
                raise ValueError(f"{key}: maximum {column.type.scale} decimal places")
