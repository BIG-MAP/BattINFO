# Packaged BattINFO cell-spec library

Reusable cell-spec records that ship inside the battinfo package, so `battinfo batch init --cell-spec` and the other batch commands find them from an installed wheel (`battinfo.api.PACKAGED_LIBRARY_CELL_SPEC_DIR`).

Each file holds one commercial cell in the library format (`specification` and `provenance`) with values taken from the manufacturer's datasheet, which `provenance` names. `CellSpec.from_path()` loads a file as a cell spec.

Your own library lives in `.battinfo/library/cell-spec/` in your working folder. Add a cell spec to it with `battinfo library save cell-spec --input <file> --no-sync-packaged-copy`.
