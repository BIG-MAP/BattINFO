**Composition is assembled, never retyped.** `salt` + `solvent_mixture.component[]` + `additive[]` each reference a `material-spec` by IRI, so an organic 1M LiPF₆ EC:EMC 3:7 and an aqueous 7M KOH are built from the LiPF6/EC/EMC/KOH material-specs. Each constituent carries its own fraction or concentration under `property`.

**Emission follows the composition.** A minimal spec types as the generic `ElectrolyteSolution`; a full formulation types by its family (`OrganicElectrolyte`, `AqueousElectrolyte`) and emits its constituents typed under `hasSolute` / `hasSolvent` / `hasAdditive`.

**Authoring rides the generic component surface** (`create_electrolyte_spec`, or `create_component_spec("electrolyte", ...)` with composition through `body=` because the class field shares its name with the function's first argument) — see [components](components.md) for the shared machinery.
