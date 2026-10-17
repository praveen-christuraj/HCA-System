# Operation quantity golden fixtures

`otms_quantity_golden.json` was produced by **executing the original OTMS source** at commit
`5eed361486fa56ad636da62e238d73059b0e2a2c`, not by executing HCA's Python engine:

- `frontend/src/utils/tankQuantityEngine.js` → `calculateTankQuantity` (four cases).
- `frontend/src/components/operationLayouts/MultiTankBeforeAfterLayout.jsx` → the pure local
  conversion helpers and `computeStage` (three cases).
- `frontend/src/components/operationLayouts/FlowmeterReadingLayout.jsx` → `pushPayload`, capturing
  its `handleValueChange` result (two cases).

The stage fixtures use a **synthetic** `0.133` LT factor at the computed API@60. It is not a
licensed/certified Table 11 dataset and must never be seeded into production. Tank cases exercise
the original approximate mass fallback; meter cases include mixed `m3` and `bbls` units.

Coverage includes API vs density input, °C/°F conversion, stage-specific API rounding, CCF before
aggregation, per-tank dictionary keys, signed/zero quantity handling and unrounded meter totals.
The source commit, input curves, inputs and expected outputs are all embedded in the fixture.
Regenerating expectations requires reviewing changes against the source; do not regenerate them
from the implementation under test to make a failing calculation test pass.
