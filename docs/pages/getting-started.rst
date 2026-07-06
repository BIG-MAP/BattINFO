Get Started
===========

BattINFO is the semantic data layer for battery science. It gives you:

- A Python library and CLI for authoring, validating, and publishing canonical battery metadata
- JSON Schema validation for cell specs, cell instances, tests, and datasets
- Automatic JSON → JSON-LD conversion aligned with the EMMO Battery Domain Ontology
- A reusable cell-spec library backed by canonical records in ``battinfo-records``


Installation
------------

BattINFO requires Python 3.11 or later.

.. code-block:: bash

   pip install battinfo

Or install from source for the latest development version:

.. code-block:: bash

   git clone https://github.com/BIG-MAP/BattINFO.git
   cd BattINFO
   pip install -e ".[dev]"


Your first cell-spec record
---------------------------

The fastest path is the ``publish`` shortcut:

.. code-block:: python

   from battinfo import CellSpec, publish

   cell_spec = CellSpec(
       manufacturer="Energizer",
       model="CR2032",
       format="coin",
       chemistry="Li-primary",
   )

   result = publish(cell_spec, destination="local")
   print(result.debug_paths)

This validates the record, assigns it a stable BattINFO IRI, and writes the canonical JSON file to ``.battinfo/``.


Linking a cell instance, test, and dataset
------------------------------------------

Use ``Workspace`` to build a fully linked chain of records:

.. code-block:: python

   from pathlib import Path
   from battinfo import Workspace

   workspace = Workspace(root=Path(".battinfo/demo"))

   cell_spec = workspace.cell_spec(
       manufacturer="Energizer",
       model="CR2032",
       format="coin",
       chemistry="Li-primary",
   )
   cell = workspace.cell(cell_spec, serial_number="LAB-001")

   protocol = workspace.test_spec(
       name="Constant current discharge",
       kind="capacity_check",
   )
   test = workspace.test(cell, protocol_ref=protocol, instrument="Landt CT2001A")
   dataset = workspace.dataset(cell, title="CR2032 baseline", test=test, path="data/run1.csv")

   workspace.save()

All records are saved to ``.battinfo/demo/`` with cross-references validated automatically.


CLI quick reference
-------------------

BattINFO ships a command-line interface for validation and querying:

.. code-block:: bash

   # Validate a cell-spec record
   battinfo validate examples/cell-spec/A123__ANR26650M1-B.json --profile cell-spec

   # Query all registered cell specs
   battinfo query cell-spec

   # Save a cell instance from a draft file
   battinfo save cell-instance --input draft.json --source-root examples

See the :doc:`../cli-spec` page for the full CLI reference.


What to read next
-----------------

.. grid:: 2

    .. grid-item-card::
        :link: ../guides/01-concepts.html

        :octicon:`book;1em;sd-text-info`  Guide notebooks
        ^^^^^^^^^^^^^^^^
        Work through the five guide notebooks covering concepts, authoring, linking, and the semantic layer.

    .. grid-item-card::
        :link: ../python-api.html

        :octicon:`code;1em;sd-text-info`  Python API reference
        ^^^^^^^^^^^^^^^^^^^^^^
        Full surface documentation for ``Workspace``, ``CellSpec``, ingest helpers, and publishing utilities.

    .. grid-item-card::
        :link: ../ontology-profile-architecture.html

        :octicon:`gear;1em;sd-text-info`  Concepts
        ^^^^^^^^
        How BattINFO relates to domain-battery, EMMO, and the Linked Data stack.

    .. grid-item-card::
        :link: ../validation-contract.html

        :octicon:`shield-check;1em;sd-text-info`  Validation
        ^^^^^^^^^^
        Validation policies and the machine-readable issue contract.
