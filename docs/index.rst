
.. toctree::
   :hidden:

   pages/getting-started
   pages/guides
   pages/howto
   pages/reference
   pages/concepts


BattINFO
========

**BattINFO** is the semantic data layer for battery science — a Python library, CLI, and canonical asset suite that validates, maps, and publishes battery metadata as machine-readable Linked Data aligned with the `EMMO Battery Domain Ontology <https://emmo-repo.github.io/domain-battery/>`_.

Here is a minimal example that creates a canonical cell-spec record and publishes it locally. It uses the same flagship cell shown on `battinfo.org <https://battinfo.org>`_ (A123 ANR26650M1-B); the full canonical record lives at ``examples/cell-spec/A123__ANR26650M1-B.json``.

.. tab-set::

   .. tab-item:: Python

      .. code-block:: python

         from battinfo import CellSpec, publish

         spec = CellSpec(
             manufacturer="A123",
             model="ANR26650M1-B",
             format="cylindrical",
             chemistry="Li-ion",
             nominal_capacity={"value": 2.5, "unit": "Ah"},
         )

         result = publish(spec, destination="local")
         # → writes a canonical BattINFO record with a persistent spec IRI

   .. tab-item:: Canonical record (JSON)

      .. code-block:: json

         {
           "schema_version": "0.1.0",
           "cell_spec": {
             "id": "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
             "name": "A123 ANR26650M1-B",
             "model": "ANR26650M1-B",
             "manufacturer": { "type": "Organization", "name": "A123" },
             "category": "battery cell",
             "cell_format": "cylindrical",
             "chemistry": "Li-ion",
             "positive_electrode_basis": "LFP"
           },
           "properties": {
             "nominal_capacity": { "value": 2.5, "unit": "Ah" },
             "nominal_voltage":  { "value": 3.3, "unit": "V" }
           }
         }

   .. tab-item:: Linked Data (JSON-LD)

      .. code-block:: json

         {
           "@context": "https://w3id.org/battinfo/context/domain-battery.jsonld",
           "@id": "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
           "@type": ["BatteryCell", "CylindricalBattery", "LithiumIonBattery"],
           "skos:prefLabel": "A123 ANR26650M1-B",
           "manufacturer": { "@type": "Organization", "name": "A123" },
           "hasProperty": [
             {
               "@type": ["NominalCapacity", "ConventionalProperty"],
               "hasNumericalPart": { "@type": "Real", "hasNumericalValue": 2.5 },
               "hasMeasurementUnit": "https://w3id.org/emmo#AmpereHour"
             }
           ]
         }


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
        Ontology architecture, the spec-and-instance model, and how BattINFO is built.

    .. grid-item-card::
        :link: how-battinfo-is-built.html

        :octicon:`stack;1em;sd-text-info`  How BattINFO is built
        ^^^^^^^^^^^^^^^^^^^^^
        The orientation roadmap: layers, data flow, and where each module fits.
