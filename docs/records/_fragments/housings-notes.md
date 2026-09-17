**Holder + property, like everything else.** `case`, `cap`, `terminals`, `seals` and the open `parts[]` list each carry identity fields plus `{value, unit}` quantities. Part types resolve to their EMMO classes — `CoinCase`, `CellLid`, `Terminal`, `Spring`, `Spacer`, `Gasket`, `SafetyVent`, `CurrentInterruptDevice` — published in domain-electrochemistry 0.36.0 for exactly this layer.

**The housing is the assembly, not the case.** The case is one of its parts (EMMO's `CellLid` "closes the case"; terminals and seals are siblings), so the described individual types `ElectrochemicalComponent` — no `CellHousing` class is published yet; it is on the upstream ask list — and every part lists uniformly under `hasConstituent`. A cell keeps the published `hasCase` pattern for its case.

**Inline or standalone.** A cell spec may describe its housing inline (the engineering-cell description path) or reference this record via `housing_spec_id`; a purchased coin-cell kit (case + cap + spring + spacer, one product id) is the classic standalone case.

**Generated surface.** `create_housing_spec` and friends wrap the shared component machinery — one registry entry per family.
