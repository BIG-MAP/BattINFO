Get Started
===========

BattINFO is the semantic data layer for battery technology. It gives you:

- A Python library and CLI for authoring, validating, and publishing canonical battery metadata
- JSON Schema validation for cell specs, cells, test specs, tests, and datasets
- Automatic JSON → JSON-LD conversion aligned with the EMMO Battery Domain Ontology
- A reusable cell-spec library backed by canonical records in ``battinfo-records``

Working at the bench? The :doc:`how-to guides <howto>` map twelve lab tasks —
register materials, build a cell from components, label cells, publish — to
short runnable recipes, and the :doc:`glossary <glossary>` decodes the
vocabulary in plain language.


Installation
------------

BattINFO requires Python 3.11 or later.

.. note::

   The package is not on PyPI yet — it publishes with the 0.8 release. Until
   then, install from source.

.. code-block:: bash

   git clone https://github.com/BIG-MAP/BattINFO.git
   cd BattINFO
   pip install -e ".[dev]"

Once 0.8 is released, ``pip install battinfo`` will work, with optional extras
that add features as you need them (each missing dependency raises an error
naming the extra to install):

.. code-block:: bash

   pip install battinfo                  # core
   pip install "battinfo[processing]"    # cycler-file conversion (ws.convert) + plotting
   pip install "battinfo[tabular]"       # CSV/Parquet/XLSX readers
   pip install "battinfo[publish]"       # RO-Crate validation for publishing


If you have data: the workspace
-------------------------------

The ``workspace`` is the one object for the whole journey — convert raw cycler
files, register the cells you tested, link tests and data, save validated
records, publish. ``ws.quickstart()`` prints the full recipe in your terminal;
the offline-safe core is:

.. doc-snippet: skip

.. code-block:: python

   import battinfo

   ws = battinfo.workspace(".")

   ws.convert()                                  # raw cycler files → tidy BDF tables

   spec = battinfo.CellSpec(                     # or reuse the registry's identity:
       manufacturer="Molicel",                   #   spec = ws.search("molicel p45b")[0]
       model="INR21700-P45B",
       format="cylindrical",
       chemistry="Li-ion",
   )
   ws.add("cell", spec=spec, serial_numbers=["S1"])
   ws.add("test", type="cycling", cell="S1", data="bdf/S1.bdf.csv")

   ws.save()                                     # validated records, stable IRIs
   # ws.login(api_key="...")                     # then: ws.publish() for the registry
   #                                             # (zenodo=True mints a citable DOI)

:doc:`Tutorial 6 — Publish your first dataset <../guides/06-publish-your-data>`
walks this exact flow against a sample Neware CSV.


If you are describing a product: record classes
------------------------------------------------

For a standalone cell-spec record — a datasheet as data — use the ``CellSpec``
record class and the ``publish`` shortcut:

.. code-block:: python

   from battinfo import CellSpec, publish

   spec = CellSpec(
       manufacturer="Energizer",
       model="CR2032",
       format="coin",
       chemistry="Li-primary",
       properties={"nominal_capacity": {"value": 0.235, "unit": "Ah"}},
   )

   result = publish(spec, destination="local")
   print(result.canonical_iri)

This validates the record, assigns it a stable BattINFO IRI, and writes the
canonical JSON file to ``.battinfo/``.


CLI quick reference
-------------------

BattINFO ships a command-line interface for validation and querying:

.. code-block:: bash

   # Validate a cell-spec record
   battinfo validate examples/cell-spec/A123__ANR26650M1-B.json --profile cell-spec

   # Query the example cell specs packaged with BattINFO (for your own
   # library, use the Python query_* functions with an explicit directory)
   battinfo query cell-spec

   # Save a cell record from a draft file
   battinfo save cell-instance --input draft.json --source-root examples

See the :doc:`CLI reference <cli-reference>` for every command.


What to read next
-----------------

.. grid:: 2

    .. grid-item-card::
        :link: guides.html

        :octicon:`book;1em;sd-text-info`  Tutorials
        ^^^^^^^^^
        Six notebooks, one story — concepts, authoring, linked records, the semantic layer, and publishing.

    .. grid-item-card::
        :link: api-reference.html

        :octicon:`code;1em;sd-text-info`  Python API
        ^^^^^^^^^^
        How the Python surface is organized: the record classes, the workspace, and the ``api`` module.

    .. grid-item-card::
        :link: ../how-battinfo-is-built.html

        :octicon:`gear;1em;sd-text-info`  How BattINFO is built
        ^^^^^^^^^^^^^^^^^^^^^
        The orientation roadmap: layers, data flow, and where each module fits.

    .. grid-item-card::
        :link: ../validation-contract.html

        :octicon:`shield-check;1em;sd-text-info`  Validation
        ^^^^^^^^^^
        Validation policies and the machine-readable issue contract.
