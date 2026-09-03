An electrolyte follows the spec + instance pattern: the **electrolyte spec**
is the formulation — its required `family` (the broad class: organic, aqueous,
…) and its composition — and the **electrolyte** record is a physical batch
mixed to that formulation.

The composition is assembled from materials, not retyped: `electrolyte-spec`
carries `salt` + `solvent_mixture.component[]` + `additive[]`, each able to
reference a `material-spec` by IRI — so an **organic 1M LiPF₆ EC:EMC 3:7**
and an **aqueous 7M KOH** are built from the LiPF6/EC/EMC/KOH material-specs
and emit `OrganicElectrolyte` / `AqueousElectrolyte` JSON-LD with
`hasSolute`/`hasSolvent`.

Authoring rides the same generic component surface as the other families
(`create_electrolyte_spec` / `create_component_spec("electrolyte", …)`); see
[Components](components.md) for the shared machinery and naming convention.
