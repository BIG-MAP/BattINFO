# Fixture: BattINFO Converter version matrix

`converter-v*.coincell.jsonld` are **real outputs** of the BattInfoConverter
tool's `convert_excel_to_jsonld`, run on its own *filled* reference templates
across the tool's version history. They drive
`tests/test_converter_version_matrix.py`, which proves BattINFO's converter
importer handles outputs produced by converter versions over the years.

## Source

- **Tool:** BattInfoConverter (`battinfoconverter_backend.convert_excel_to_jsonld`),
  held at the `battery-genome/BattInfoConverter` checkout, outside this package.
- **Inputs:** the *filled* templates under `BattInfoConverter/Excel for reference/`.
- All outputs are a single **CoinCell-root** JSON-LD document (this tool does not
  emit the `@graph` / `BatteryTest-root` shapes — those come from EMPA RO-Crate
  exports, covered separately by `tests/fixtures/converter/`).

## Versions pinned

| Fixture | Template version | Component holder |
|---------|------------------|------------------|
| `converter-v1.0.0`  | 1.0.0  | `hasConstituent` |
| `converter-v1.1.2`  | 1.1.2  | `hasConstituent` |
| `converter-v1.1.8`  | 1.1.8  | `hasConstituent` |
| `converter-v1.1.11` | 1.1.11 | `hasConstituent` |
| `converter-v1.1.15` | 1.1.15 | `hasComponent`   |
| `converter-v1.1.17` | 1.1.17 | `hasComponent`   |

The spread spans the tool's naming change (Battery2030+ → BattINFO standard) and
the key structural drift — the cell-component holder switched from
`hasConstituent` to `hasComponent` between v1.1.11 and v1.1.15. Both shapes must
import; the test asserts the set covers both.

## Regenerating

```
uv run --with simplejson python scripts/generate_converter_version_fixtures.py \
    --converter-root "<path>/battery-genome/BattInfoConverter"
```

Filled templates contain fixed dates, so conversion is deterministic. The
fixtures are committed JSON-LD, so the test needs no BattInfoConverter
dependency at run time.
