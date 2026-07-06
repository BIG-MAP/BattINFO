// Example fixtures for the website.
//
// SINGLE SOURCE OF TRUTH: the authored-input record comes from examples/** in
// the repo, surfaced via the generated module below (run `npm run sync:examples`
// to regenerate). The full example content must come from examples/** — only
// short, curated teasers (the hero / install / Python snippets, and the
// illustrative JSON-LD that the Python transform can't yet emit as a file) live
// inline here. See docs/CONTENT-MODEL.md §4.

export { cellSpecInput, cellSpecCanonical } from "./examples.generated";

// The hero: the data-first publishing journey, condensed from ws.quickstart().
// DO NOT EDIT the ws.* calls freely — tests/test_web_snippets.py asserts every
// ws.<verb> here appears (in order) in the recipe ws.quickstart() prints, so
// the homepage can never teach a different sequence than the library does.
export const publishJourneySnippet = `import battinfo
ws = battinfo.workspace(".")

ws.convert()                          # cycler files -> tidy tables
spec = ws.search("molicel p45b")[0]   # find your cell
ws.add("cell", spec=spec, serial_numbers=["S1", "S2"])
ws.add("test", type="cycling", cell="S1", data="bdf/S1.bdf.csv")

ws.save()                             # validated records + stable IRIs
ws.publish(zenodo=True)               # citable DOI + registry`;

// A deliberately friendly, single-record snippet — plain authored JSON, NOT
// JSON-LD. Used where we show how readable the authored records are; the
// Linked Data machinery is shown later (Examples page).
export const heroSnippet = `{
  "name": "A123 ANR26650M1-B",
  "manufacturer": "A123",
  "chemistry": "Li-ion",
  "format": "cylindrical",
  "nominal_capacity": { "value": 2.5, "unit": "Ah" },
  "nominal_voltage":  { "value": 3.3, "unit": "V" }
}`;

export const quickstartPython = `from battinfo import CellSpec, publish

result = publish(
    CellSpec(
        manufacturer="A123",
        model="ANR26650M1-B",
        cell_format="cylindrical",
        chemistry="Li-ion",
        nominal_capacity={"value": 2.5, "unit": "Ah"},
    ),
    destination="local",
)
print(result.canonical_iri)
# https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5`;

export const installSnippet = `python -m venv .venv
.venv/bin/pip install battinfo`;
