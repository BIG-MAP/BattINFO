# How-to guides

Task-first recipes for people who already know the basics. Each link is a short
recipe you can run today; none of them require reading the architecture pages
first. New to BattINFO? The {doc}`tutorials <guides>` teach the model these
recipes assume, and the [glossary](glossary.md) decodes the vocabulary.

| I want to… | Recipe |
|---|---|
| **Register the materials** in my lab (actives, binders, salts, solvents) | [Register materials](../howto/register-materials.md) |
| **Describe an electrode recipe** (96/2/2 coating, loading, thickness) | {ref}`Build a cell from components, electrodes <electrode-recipe>` |
| **Describe a cell I built** from its parts (electrodes, electrolyte, separator, housing) | [Build a cell from components](../howto/build-a-cell-from-components.md) |
| **Log the cells on my bench** (lab names, no serial numbers) | [Label your cells](../howto/label-your-cells.md) |
| **Register my cycler and its channels** | [Register equipment](../howto/register-equipment.md) |
| **Define a test protocol** (CC-CV cycling, capacity check, EIS, …) | [Test specs](../test-specs.md) |
| **Log a test run** linked to a cell, a protocol, and a channel | [Workspace authoring](../workspace-authoring.md) · [Tutorial 3, Linked records](../guides/03-linked-records.ipynb) |
| **Convert a cycler export** to a tidy table (NEWARE, Biologic, Maccor CSV, …) | [Tutorial 6, Stage 1: Convert](../guides/06-publish-your-data.ipynb) · unmapped columns? see [troubleshooting](troubleshooting.md#converted-file-is-missing-columns) |
| **Validate my records and fix what's wrong** | [Fix validation errors](../howto/fix-validation-errors.md) |
| **Publish, and get a DOI** | [Tutorial 6, Publish your first dataset](../guides/06-publish-your-data.ipynb) |
| **Put labels / QR codes on my cells** | [Label your cells](../howto/label-your-cells.md) |
| **Find out what already exists** (my session, my library, the registry) | [Find existing records](../howto/find-existing-records.md) |
| **Ingest a whole folder** of raw data files at once | [Bulk ingest](../howto/bulk-ingest.md) |
| **Resume a submission** I started earlier | [Resume a submission](../howto/resume-a-submission.md) |
| **Tag records with funding and my ORCID** | [Tag funding and ORCID](../howto/tag-funding-and-orcid.md) |

## When something doesn't work

The [troubleshooting page](troubleshooting.md) covers the classic surprises:
empty search results, template files that will not load, columns that vanish
in conversion, IRIs that open a sign-in page, and validation errors about
dates.

## The 30-second orientation

Everything in BattINFO is a **spec** (a reusable description: a material
grade, a cell product, a test protocol) or an **instance** (a physical thing
or event: this cell, this test run). You register specs once, point instances
at them, and every saved record gets a permanent IRI you can print on a label
or cite in a paper. The {doc}`tutorials <guides>` build this up properly.

```{toctree}
:maxdepth: 1
:caption: Recipes

../workspace-authoring
../howto/register-materials
../howto/build-a-cell-from-components
../howto/label-your-cells
../howto/register-equipment
../howto/find-existing-records
../howto/bulk-ingest
../howto/fix-validation-errors
../howto/resume-a-submission
../howto/tag-funding-and-orcid
troubleshooting
```
