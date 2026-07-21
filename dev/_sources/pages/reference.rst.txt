Reference
=========

Facts about the surface: every class, command, schema, property, and guarantee.
The pages descend from what you call, to what comes out, to what is promised. The
generated pages are produced from the code and mapping tables and drift-checked
in CI, so they cannot rot.

Surfaces
--------

The two generated surfaces you call against: the Python API and the CLI. For the
workspace, the everyday way most people author records, see the how-to guides.

.. toctree::
   :maxdepth: 1

   api-reference
   cli-reference

Record types
------------

One page per record family: the fields each carries, and how they link.

.. toctree::
   :maxdepth: 1

   ../material-spec
   ../component-specs
   ../cell-fleet
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

Glossary
--------

.. toctree::
   :maxdepth: 1

   glossary
