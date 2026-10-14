Get Started
===========

BattINFO is the semantic data layer for battery technology. It gives you:

- A Python library and CLI for authoring, validating, and publishing canonical battery metadata
- JSON Schema validation for cell specs, cells, test specs, tests, and datasets
- Automatic JSON → JSON-LD conversion aligned with the EMMO Battery Domain Ontology
- A reusable cell-spec library backed by canonical records in ``battinfo-records``

Working at the bench? The :doc:`how-to guides <howto>` map lab tasks, such as registering materials, building a cell from components, labelling cells and publishing, to short runnable recipes, and the :doc:`glossary <glossary>` decodes the vocabulary in plain language.


Installation
------------

BattINFO supports Python 3.11–3.14. Until 0.8.0, its first working release on PyPI, install it from GitHub. The optional extras add features as you need them, and a feature whose dependency is missing raises an error that names the extra to install:

.. code-block:: bash

   pip install "battinfo @ git+https://github.com/BIG-MAP/BattINFO.git"              # core
   pip install "battinfo[processing] @ git+https://github.com/BIG-MAP/BattINFO.git"  # cycler-file conversion (ws.convert) + plotting
   pip install "battinfo[tabular] @ git+https://github.com/BIG-MAP/BattINFO.git"     # CSV/Parquet/XLSX readers
   pip install "battinfo[publish] @ git+https://github.com/BIG-MAP/BattINFO.git"     # RO-Crate validation for publishing

.. note::

   The ``processing`` extra requires ``batterydf[nda,excel,mat]>=0.2.0rc2,<0.3``, so pip installs the batterydf 0.2.0 release candidate until 0.2.0 itself is published.

A hosted notebook such as Colab starts without BattINFO. Install it in a cell before you import it; the second line adds the ``processing`` extra, which tutorial 6 needs:

.. code-block:: text

   %pip install "battinfo @ git+https://github.com/BIG-MAP/BattINFO.git"
   %pip install "battinfo[processing] @ git+https://github.com/BIG-MAP/BattINFO.git"

To work on BattINFO itself, clone the repository and follow the `contributing guide <https://github.com/BIG-MAP/BattINFO/blob/main/CONTRIBUTING.md>`_.


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
   # The serial printed on the cell, or a label only your lab uses: a cell's
   # IRI comes from its spec and serial, so a bare "S1" would be every lab's S1.
   ws.add("cell", spec=spec, serial_numbers=["MYLAB-P45B-001"])
   ws.add("test", type="cycling", cell="MYLAB-P45B-001", data="bdf/MYLAB-P45B-001.bdf.csv")

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
       chemistry="li-mno2",
       rechargeable=False,
       properties={"nominal_capacity": {"value": 0.235, "unit": "Ah"}},
   )

   result = publish(spec, destination="local")
   print(result.canonical_iri)

This validates the record, assigns it a stable BattINFO IRI, and writes the
canonical JSON to a local ``.battinfo/`` tree.

.. note::

   The printed IRI is **permanent, but not yet resolvable on the web** —
   opening ``https://w3id.org/battinfo/spec/...`` in a browser returns 404 for
   a record published locally. It becomes resolvable once you publish the
   record to the registry (see :doc:`Tutorial 6 — Publish your first dataset
   <../guides/06-publish-your-data>`). A local publish mints the identity; the
   registry makes it dereferenceable.

**What you just created.** ``destination="local"`` writes to a ``.battinfo/``
directory. It is a dot-directory, so a plain ``ls`` hides it — use ``ls -a``:

.. code-block:: text

   .battinfo/publish/energizer-cr2032/          # one folder per record, named from the spec
   ├── index.json
   └── examples/cell-spec/cell-spec-<id>.json   # the canonical record JSON


CLI quick reference
-------------------

BattINFO ships a command-line interface for validation and querying. The example records that come with the package can be searched from any folder:

.. code-block:: bash

   battinfo query cell-spec --include-packaged-examples

The commands below continue from the CR2032 cell spec published above. Replace ``<id>`` with the end of the IRI it printed (``https://w3id.org/battinfo/spec/<id>``):

.. doc-snippet: skip

.. code-block:: bash

   # Validate the cell spec record
   battinfo validate .battinfo/publish/energizer-cr2032/examples/cell-spec/cell-spec-<id>.json

   # Write a draft for a physical cell of that spec
   battinfo template cell-instance --cell-spec-id https://w3id.org/battinfo/spec/<id> --out draft.json

   # Set "serial_number" under "cell_instance" in draft.json, then save the cell
   # next to its spec, where the reference to the spec resolves
   battinfo save cell-instance --input draft.json --source-root .battinfo/publish/energizer-cr2032/examples

``battinfo validate`` takes any record file, one you created or downloaded. The example records shipped with the package are JSON files in the ``data/examples`` folder of the installed package; this prints where that is:

.. code-block:: bash

   python -c "import battinfo, pathlib; print(pathlib.Path(battinfo.__file__).parent / 'data' / 'examples')"

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
        :link: ../guarantees.html#validation-contract

        :octicon:`shield-check;1em;sd-text-info`  Validation
        ^^^^^^^^^^
        Validation policies and the machine-readable issue contract.
