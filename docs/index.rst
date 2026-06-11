
.. toctree::
   :hidden:

   pages/getting-started
   pages/guides
   pages/reference
   pages/concepts


BattINFO
========

**BattINFO** is the semantic data layer for battery science — a Python library, CLI, and canonical asset suite that validates, maps, and publishes battery metadata as machine-readable Linked Data aligned with the `EMMO Battery Domain Ontology <https://emmo-repo.github.io/domain-battery/>`_.

Here is a minimal example that creates a canonical cell-type record and publishes it locally:

.. tab-set::

   .. tab-item:: Python

      .. code-block:: python

         from battinfo import CellType, publish

         cell_type = CellType(
             manufacturer="Energizer",
             model="CR2032",
             format="coin",
             chemistry="Li-primary",
         )

         result = publish(cell_type, destination="local")
         # → writes a canonical BattINFO record under .battinfo/

   .. tab-item:: Canonical record (JSON)

      .. code-block:: json

         {
           "product": {
             "id": "https://w3id.org/battinfo/cell/...",
             "short_id": "...",
             "manufacturer": "Energizer",
             "model": "CR2032",
             "format": "coin",
             "chemistry": "Li-primary"
           },
           "provenance": {
             "source_type": "lab",
             "retrieved_at": "2025-05-15"
           }
         }

   .. tab-item:: Linked Data (JSON-LD)

      .. code-block:: json

         {
           "@context": "https://w3id.org/battinfo/context.json",
           "@type": "battinfo:CellType",
           "@id": "https://w3id.org/battinfo/cell/...",
           "schema:manufacturer": "Energizer",
           "schema:name": "CR2032",
           "battinfo:format": "coin",
           "battinfo:chemistry": "Li-primary"
         }


Explore the documentation
--------------------------

.. grid:: 2

    .. grid-item-card::
        :link: pages/getting-started.html

        :octicon:`rocket;1em;sd-text-info`  Get Started
        ^^^^^^^^^^^
        Install BattINFO and publish your first cell-type record in five minutes.

    .. grid-item-card::
        :link: pages/guides.html

        :octicon:`book;1em;sd-text-info`  Guides
        ^^^^^^^
        Step-by-step notebooks covering concepts, cell types, linked records, and the semantic layer.

.. grid:: 2

    .. grid-item-card::
        :link: pages/reference.html

        :octicon:`code;1em;sd-text-info`  Reference
        ^^^^^^^^^
        Python API, CLI commands, and the validation policy contract.

    .. grid-item-card::
        :link: pages/concepts.html

        :octicon:`gear;1em;sd-text-info`  Concepts
        ^^^^^^^^
        Ontology architecture, authoring workflows, and the Linked Data model.
