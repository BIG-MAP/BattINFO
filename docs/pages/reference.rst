Reference
=========

Facts about the surface, descending from what you call, to what a correct
record looks like, to how each family is modeled, to what is promised. The
generated pages are produced from the code and mapping tables and
drift-checked in CI, so they cannot rot.

Surfaces
--------

The two generated surfaces you call against: the Python API and the CLI. For the
workspace, the everyday way most people author records, see the how-to guides.

.. toctree::
   :maxdepth: 1

   api-reference
   cli-reference

Reference records
-----------------

One exemplar per record type: the authoring code, the canonical record it
produces, and the JSON-LD that record emits — generated against the current
library and drift-gated, so they always show what the code does today.

.. toctree::
   :maxdepth: 1

   ../records/index

Record models
-------------

How each record family is modeled: the levels, the fields, the links between
records, and the design decisions behind them.

.. toctree::
   :maxdepth: 1

   ../materials-model
   ../material-spec
   ../electrodes-model
   ../component-specs
   ../cell-fleet
   ../engineering-cell-description
   ../test-specs

Schemas and properties
----------------------

The JSON Schemas the records are checked against, and the property and unit
vocabulary.

.. toctree::
   :maxdepth: 1

   schema-reference
   property-reference

Contracts
---------

What the infrastructure guarantees, and the interfaces you can build against.

.. toctree::
   :maxdepth: 1

   ../validation-contract
   contract
   ../ingest-manifest-contract
   interop-recovery

Scope and support
-----------------

The capability map: what is supported today, what is preview, what is in
development, and the modeling boundary (cell level and below).

.. toctree::
   :maxdepth: 1

   ../scope

Glossary
--------

.. toctree::
   :maxdepth: 1

   glossary
