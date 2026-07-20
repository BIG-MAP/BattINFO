Reference
=========

Facts about the surface: every class, command, schema, property, and guarantee.
The pages descend from what you call, to what comes out, to what is promised. The
generated pages are produced from the code and mapping tables and drift-checked
in CI, so they cannot rot.

Surfaces
--------

Start here: the Python API and the CLI, plus the workspace, the everyday way most
people author records.

.. toctree::
   :maxdepth: 1

   api-reference
   ../workspace-authoring
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

Glossary
--------

.. toctree::
   :maxdepth: 1

   glossary
