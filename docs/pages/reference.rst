Reference
=========

Organized by the question you arrive with: what you call, what a record of
each type looks like, what records emit semantically, what the infrastructure
promises, and what is supported today. The generated pages are produced from
the code, schemas, and mapping tables and drift-checked in CI, so they cannot
rot.

What you call
-------------

The two generated surfaces: the Python API and the CLI. For the workspace,
the everyday way most people author records, see the how-to guides.

.. toctree::
   :maxdepth: 1

   api-reference
   cli-reference

Record types
------------

One page per record family, and each page is the whole story: what the thing
is, a reference example (authoring code, the canonical record, its JSON-LD),
and the field reference from the JSON Schemas. When someone asks how to
describe a cell, a material, or a separator — the answer is one link.

.. toctree::
   :maxdepth: 1

   ../records/index

What records emit
-----------------

The semantic layer: the property and unit vocabulary behind every quantity.
For the anatomy of a published JSON-LD document, see
:doc:`../reading-a-record` (under Concepts).

.. toctree::
   :maxdepth: 1

   property-reference

Guarantees
----------

What the infrastructure promises, and the interfaces you can build against.
Each contract names its audience: the infrastructure contract is for the
person building *on* BattINFO, the validation contract for the person
integrating validation, the ingest manifest contract for the person feeding
bulk data in.

.. toctree::
   :maxdepth: 1

   contract
   ../validation-contract
   ../ingest-manifest-contract

Status
------

What is supported today, what is preview, and how well each external data
source round-trips.

.. toctree::
   :maxdepth: 1

   ../scope
   interop-recovery

Glossary
--------

.. toctree::
   :maxdepth: 1

   glossary

.. toctree::
   :hidden:

   ../materials-model
   ../material-spec
   ../electrodes-model
   ../component-specs
   ../test-specs
   schema-reference
