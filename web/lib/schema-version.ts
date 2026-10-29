// The `schema_version` the form stamps on every draft.
//
// Read from the synced example corpus rather than written down here:
// examples.generated.ts is generated from examples/**, which is the package's
// own source of truth, so the stamp cannot drift from the records the library
// writes. It used to be a constant in the Create page's emitter with a CI
// check holding the two equal (`check:create-model`); that check is gone
// because there are no longer two things to hold equal.

import { cellSpecCanonical } from "./examples.generated";

export const SCHEMA_VERSION = String(cellSpecCanonical.schema_version);
