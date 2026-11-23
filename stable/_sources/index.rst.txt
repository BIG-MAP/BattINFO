
.. toctree::
   :hidden:

   pages/getting-started
   pages/guides
   pages/howto
   pages/reference
   pages/concepts
   community/index


BattINFO
========

**BattINFO** is the semantic data layer for battery technology — a Python library, CLI, and canonical asset suite that validates, maps, and publishes battery metadata as machine-readable Linked Data aligned with the `EMMO Battery Domain Ontology <https://emmo-repo.github.io/domain-battery/>`_.

Here is a minimal example that describes a cell spec in Python and saves it locally. The other two tabs show the flagship cell from `battinfo.org <https://battinfo.org>`_, the A123 ANR26650M1-B: its record as stored in ``examples/cell-spec/A123__ANR26650M1-B.json``, and the JSON-LD that ``battinfo.record_to_jsonld`` writes for that record.

.. tab-set::

   .. tab-item:: Python

      .. code-block:: python

         from battinfo import CellSpec, publish

         spec = CellSpec(
             manufacturer="A123",
             model="ANR26650M1-B",
             format="cylindrical",
             chemistry="li-ion",
             nominal_capacity={"value": 2.5, "unit": "Ah"},
         )

         # publish() gives this spec its own IRI, minted from its manufacturer,
         # model, format, chemistry and size code. The flagship record in the
         # next two tabs has more fields and keeps the IRI it was published
         # under, so the two IRIs differ.
         result = publish(spec, destination="local")
         print(result.canonical_iri)

   .. tab-item:: Flagship record (JSON)

      .. literalinclude:: ../examples/cell-spec/A123__ANR26650M1-B.json
         :language: json

   .. tab-item:: Flagship JSON-LD

      .. literalinclude:: ../web/public/jsonld/cell-spec.jsonld
         :language: json


Explore the documentation
--------------------------

The documentation follows the `Diátaxis <https://diataxis.fr/>`_ structure:
**tutorials** teach, **how-to guides** solve one task each, **reference**
states the facts, and **concepts** explain the design.

.. grid:: 2

    .. grid-item-card::
        :link: pages/getting-started.html

        :octicon:`rocket;1em;sd-text-info`  Get Started
        ^^^^^^^^^^^
        Install BattINFO and publish your first records in five minutes.

    .. grid-item-card::
        :link: pages/guides.html

        :octicon:`book;1em;sd-text-info`  Tutorials
        ^^^^^^^^^
        Six notebooks, one story — from the record model to a published, citable dataset.

.. grid:: 2

    .. grid-item-card::
        :link: pages/howto.html

        :octicon:`checklist;1em;sd-text-info`  How-to guides
        ^^^^^^^^^^^^^
        Task-shaped recipes: bulk ingest, fixing validation errors, resuming submissions, funding tags.

    .. grid-item-card::
        :link: pages/reference.html

        :octicon:`code;1em;sd-text-info`  Reference
        ^^^^^^^^^
        Python API, CLI commands, schemas, and the validation policy contract.

.. grid:: 2

    .. grid-item-card::
        :link: pages/concepts.html

        :octicon:`gear;1em;sd-text-info`  Concepts
        ^^^^^^^^
        How records read as linked data, the ontology architecture, and how BattINFO is built.

.. grid:: 2

    .. grid-item-card::
        :link: community/index.html

        :octicon:`people;1em;sd-text-info`  Community
        ^^^^^^^^^
        Monthly office hours: slides, notes, and the questions raised on each call.
