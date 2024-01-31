
.. toctree::
   :includehidden:
   :hidden:

   Get Started <getstarted>
   Examples <examples>
   Class Index <battinfo>
   About <about>
   FAQ <faq>

Battery Interface Ontology
================================

Welcome to the **Battery Interface Ontology (BattINFO)**, a semantic resource with essential terms and relationships to describe battery cells, materials, methods, and data. **Here's a simple example:**

.. tab-set::

   .. tab-item:: JSON

      .. code-block:: json
         :linenos:

         {
            "@context": "https://raw.githubusercontent.com/emmo-repo/domain-battery/master/context.json",
            "@type": "CR2032",
            "schema:name": "My CR2032 Coin Cell",
            "schema:manufacturer": {
               "@id": "https://www.wikidata.org/wiki/Q3041255",
               "schema:name": "SINTEF"
            },
            "hasProperty": {
               "@type": ["NominalCapacity", "ConventionalProperty"],
               "hasNumericalPart": {
                     "@type": "Real",
                     "hasNumericalValue": 230
               },
               "hasMeasurementUnit": "emmo:MilliAmpereHour"
            }
         }

   .. tab-item:: JSON-LD Playground

      .. raw:: html
         
         <div style="position: relative; padding-top: 56.25%; height: 0;">
            <iframe src="https://json-ld.org/playground/#startTab=tab-table&json-ld=%7B%22%40context%22%3A%22https%3A%2F%2Fraw.githubusercontent.com%2Femmo-repo%2Fdomain-battery%2Fmaster%2Fcontext.json%22%2C%22%40type%22%3A%22CR2032%22%2C%22schema%3Aname%22%3A%22My%20CR2032%20Coin%20Cell%22%2C%22schema%3Amanufacturer%22%3A%7B%22%40id%22%3A%22https%3A%2F%2Fwww.wikidata.org%2Fwiki%2FQ3041255%22%2C%22schema%3Aname%22%3A%22SINTEF%22%7D%2C%22hasProperty%22%3A%7B%22%40type%22%3A%5B%22NominalCapacity%22%2C%22ConventionalProperty%22%5D%2C%22hasNumericalPart%22%3A%7B%22%40type%22%3A%22Real%22%2C%22hasNumericalValue%22%3A230%7D%2C%22hasMeasurementUnit%22%3A%22emmo%3AMilliAmpereHour%22%7D%7D" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" frameborder="0" allowfullscreen></iframe>
         </div>


Check out these resources to get started!
-----------------------------------------
.. grid::

    .. grid-item-card::
        :link: getstarted.html

        :octicon:`rocket;1em;sd-text-info`  Get Started
        ^^^^^^^^^^^
        Let's go! Here is some information to help you get started

    .. grid-item-card::
        :link: electrochemistry.html

        :octicon:`book;1em;sd-text-info`  Class Index
        ^^^^^^^^^^^
        A complete list of terms and some human-readable annotations

.. grid::

    .. grid-item-card::
        :link: examples.html

        :octicon:`pencil;1em;sd-text-info`  Examples
        ^^^^^^^^
        Here are some examples that demonstrate basic usage of the ontology

    .. grid-item-card::
        :link: contribute.html

        :octicon:`thumbsup;1em;sd-text-info`  Contribute
        ^^^^^^^^^^
        Help us develop the ontology by following these guidelines