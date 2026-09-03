A parameter set is a batch of parameter **claims** about a material kind or
other target: each claim names a parameter from the curated parameter
vocabulary, a `{value, unit}` quantity (or a curve), and a provenance class
(literature, measured, fitted, assumed). Claims are deliberately records —
several sources can claim different values for the same parameter, and a
consumer selects among them rather than being handed one anonymous number.
The parameter vocabulary and the model-tier completeness contracts live in
the packaged `parameters.json`; the resolve endpoint applies the same rules.
