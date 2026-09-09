**Composition is assembled, never retyped.** `salt` + `solvent` + `additive[]` each reference a `material-spec` by IRI, so an organic 1M LiPF₆ EC:EMC 3:7 and an aqueous 7M KOH are built from the LiPF6/EC/EMC/KOH material-specs. Each constituent carries its own fraction or concentration under `property`. The salt's ions and chemistry follow from its material identity (the kind resolves to the chemical-substance class); the old `cation`/`anion` strings stay accepted as deprecated keys, never taught.

**One solvent or many.** `solvent` takes a single component object for a pure solvent and a list for a mixture — no wrapper level. The old `solvent_mixture: {component: [...]}` spelling stays accepted as a deprecated alias and normalizes to `solvent` on round-trip.

**Emission follows the composition.** The spec is an information artifact — it types `[Description, schema:CreativeWork]`, and the physical typing rides the anonymous individual under `isDescriptionFor`: the generic `ElectrolyteSolution` for a minimal spec, the family class (`OrganicElectrolyte`, `AqueousElectrolyte`) for a full formulation, with constituents typed under `hasSolute` / `hasSolvent` / `hasAdditive`.

**Authoring is first-class**: `create_electrolyte_spec(...)` / `create_electrolyte(...)` take the composition fields (`family=`, `salt=`, `solvent=`, `additive=`) as plain keyword arguments.
