"""OTMS Table 11 lookup over operator-supplied reference data.

No factors are invented, generated, or represented as certified. If the master
is empty the layouts show OTMS's explicit fallback / missing-reference caution.
Source: OTMS routers/table11_factors.py at 5eed361486fa56ad636da62e238d73059b0e2a2c.
"""
import math
from sqlalchemy.orm import Session
from app.models import Table11Factor


def lookup_table11_factor(api60, db: Session | None = None, *, rows=None) -> dict:
    try:
        value = float(api60)
    except (TypeError, ValueError):
        raise ValueError("API @ 60°F is required")
    if not math.isfinite(value):
        raise ValueError("API @ 60°F must be finite")
    if rows is None:
        rows = db.query(Table11Factor).order_by(Table11Factor.api60).all() if db else []
        points = [(float(r.api60), float(r.lt_factor)) for r in rows]
    else:
        points = sorted((float(a), float(f)) for a, f in rows)
    if not points:
        raise ValueError("Table 11 factor master is empty. Upload API@60 and LT factor data first.")
    exact = next((p for p in points if p[0] == value), None)
    if exact:
        lower = upper = exact
        method = "Exact match"
        factor = exact[1]
    elif value < points[0][0]:
        lower = upper = points[0]
        method, factor = "Below range - nearest factor used", lower[1]
    elif value > points[-1][0]:
        lower = upper = points[-1]
        method, factor = "Above range - nearest factor used", lower[1]
    else:
        lower = max(p for p in points if p[0] < value)
        upper = min(p for p in points if p[0] > value)
        factor = round(lower[1] + (value - lower[0]) / (upper[0] - lower[0]) * (upper[1] - lower[1]), 10)
        method = "Linear interpolation"
    return {"api60": value, "lower_api60": lower[0], "upper_api60": upper[0], "lt_factor": factor, "lookup_method": method}
