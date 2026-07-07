Concepts
========

The design, in reading order: the big picture first, then the record model
built up from materials to datasets, then the contracts the infrastructure
holds.

The big picture
---------------

.. toctree::
   :maxdepth: 1

   ../how-battinfo-is-built
   ../ontology-profile-architecture
   ../identifiers
   ../data-federation

The record model — spec and instance, from materials up
--------------------------------------------------------

Everything in BattINFO is a *spec* (the reusable description) or an
*instance* (the physical thing or event it describes). These pages walk the
model bottom-up:

.. toctree::
   :maxdepth: 1

   ../material-spec
   ../component-specs
   ../cell-type-library
   ../cell-fleet
   ../test-specs
   ../instance-test-dataset-workflow

The contracts
-------------

What the infrastructure guarantees, and the interface specifications
consumers can build against:

.. toctree::
   :maxdepth: 1

   contract
   ../ingest-manifest-contract
   ../cli-spec
