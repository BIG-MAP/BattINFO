Get Started
================================

This ontology is used mostly for generating linked data and complying with the FAIR data guidelines (although it can also do much more!). It provides machine-readable persistent identifiers for terms and semantic relations that help describe what things are and how they are related to each other.

An easy way to get started is to use the ontology vocabulary to create semantic linked data using JSON-LD files. We recommend you follow this step-by-step guide to understand the background and **make your first piece of linked data in just 5 easy steps!**

Step 1: Install Protégé
~~~~~~~~~~~~~~~~~~~~~~~

`Protégé <https://protege.stanford.edu/>`__ is a graphical ontology editor developed by Stanford University. It is free and one of the most widely used tools for ontology development. You can read more about it in the tools section. 

Step 2: Download the pre-inferred version of the ontology
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ontologies within the EMMO universe import many different modules to try to re-use knowledge and terms from other domains. We then run a tool called a "reasoner" to make logical inferrences about how terms from different domains are connected, and lump them into one ontology. 

We make it easy for you by providing a pre-inferred version in advance. You can `download it from the GitHub repository <https://github.com/emmo-repo/domain-electrochemistry/blob/master/electrochemistry-inferred.ttl>`__  or access it at anytime using this URL:

https://raw.githubusercontent.com/emmo-repo/domain-electrochemistry/master/electrochemistry-inferred.ttl

Step 3: Open and explore the ontology file in Protégé
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Within Protégé, you can explore the class hierarchy that contains all the "things" that are included in the ontology, as well as the object properties that describe how those things are related to each other. There are a few things to notice:

#. **Each item has a unique, persistent, and machine readable identifier called an IRI.** An IRI (Internationalized Reference Identifier) is the official identifier for that term. It is the anchor to which all other information is linked. In the EMMO universe, IRIs usually contain some Universal Unique Identifier (UUID) character sequence that ensures their uniqueness. For example, the IRI for ElectrochemicalCell is:

   https://w3id.org/emmo/domain/electrochemistry#electrochemistry_6f2c88c9_5c04_4953_a298_032cc3ab9b77

   Clicking the link will take you to human-readable documentation. But if the request comes from an application or if you add a trailing slash / character to the IRI, then it will take you to a machine-readable turtle file. 

   As you can see, the use of UUIDs in the IRIs make it difficult for humans to read and understand. But fear not! Each term also comes with a set of human readable labels called prefLabel and altLabel.

#. **Each item has one human-readable preferred label and can have many alternative labels.** The EMMO universe uses the SKOS terminology for labelling items. The main label for the term is called its prefLabel (short for preferred label) and is often expressed in the source files as skos:prefLabel. But sometimes, there can be multiple labels for the same thing. In that case we use skos:altLabel to list possible alternative labels.

#. **Each item has an elucidation, describing the meaning of the term.** The elucidation is a short human-readable text that describes the conceptualization for the term. It should give some insight into what the term means and how it can be used.

#. **Many terms have links to other sources of information.** For many terms, there are other authoritative sources of information available that can provide more context about its meaning. To account for that, we include annotations that point to places like the IEC Vocabulary, IUPAC Goldbook, DBpedia, WikiData, or Wikipedia where humans or machines can go to retrieve more information.

Step 4: Explore the JSON-LD context file
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

JSON-LD is one of the easiest and most common file formats for creating linked data. JSON-LD uses the same key-value pair structure of traditional JSON, but adds a few keywords to support semantic linked data. One of these is the @context keyword, which points to a dictionary that pairs human readable term labels with machine readable IRIs. For convenience, we provide a JSON-LD context file that is generated from the pre-inferred version of the ontology that pairs prefLabels with IRIs. You can find the `context file on the GitHub repository <https://github.com/emmo-repo/domain-electrochemistry/blob/master/context.json>`__  or access it anytime using this URL:

https://raw.githubusercontent.com/emmo-repo/domain-electrochemistry/master/context.json

Step 5: Make your own linked data!
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Now you can make your own piece of linked data using ontology terms and JSON-LD. Let's make a linked data description of a simple electrochemical cell consisting of a zinc negative electrode, a manganese dioxide positive electrode, and an alkaline electrolyte. This is expressed in JSON-LD as:

.. tab-set::

   .. tab-item:: JSON

      .. code-block:: json
         :linenos:

         {
            "@context": "https://raw.githubusercontent.com/emmo-repo/domain-electrochemistry/master/context.json",
            "@type": "ElectrochemicalCell",
            "hasNegativeElectrode": {
               "@type": "ZincElectrode"
            },
            "hasPositiveElectrode": {
               "@type": "ManganeseDioxideElectrode"
            },
            "hasElectrolyte": {
               "@type": "AlkalineElectrolyte"
            }
         }

   .. tab-item:: JSON-LD Playground

      .. raw:: html
         
         <div style="position: relative; padding-top: 56.25%; height: 0;">
            <iframe src="https://json-ld.org/playground/#startTab=tab-table&json-ld=%7B%22%40context%22%3A%22https%3A%2F%2Fraw.githubusercontent.com%2Femmo-repo%2Fdomain-electrochemistry%2Fmaster%2Fcontext.json%22%2C%22%40type%22%3A%22ElectrochemicalCell%22%2C%22hasNegativeElectrode%22%3A%7B%22%40type%22%3A%22ZincElectrode%22%7D%2C%22hasPositiveElectrode%22%3A%7B%22%40type%22%3A%22ManganeseDioxideElectrode%22%7D%2C%22hasElectrolyte%22%3A%7B%22%40type%22%3A%22AlkalineElectrolyte%22%7D%7D" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" frameborder="0" allowfullscreen></iframe>
         </div>


First, we use the ``@context`` keyword to establish the context for machines to process the file by pointing to our pre-inferred context file on GitHub. 

Then, we use the keyword ``@type`` to describe what type of thing we are describing, in this case an ``ElectrochemicalCell``. When a machine processes this file, it is going to check in the context and retrieve the IRI that is associated to the label ``ElectrochemicalCell``. 

Next, we use object properties that are defined in the ontology like ``hasNegativeElectrode``, ``hasPositiveElectrode``, and ``hasElectrolyte`` to define links to other things. In this example, we say that our electrochemical cell has a ngeative electrode, and that electrode is of the type ``ZincElectrode``.

Finally, you can use the `JSON-LD Playground <https://json-ld.org/playground/>`__ to see how machines can process the linked data file.

And that's it! You did it! Check out our examples to see some more advanced topics. 

We've provided some recommendations for tools and examples that you are free to re-use or modify for your own needs. 

.. grid::

    .. grid-item-card::
        :link: tools.html

        :octicon:`tools;1em;sd-text-info`  Tools
        ^^^^^^^^^^^
        The right tool for the right job. Here are some tools that can help you work with ontologies, knowledge graphs, and linked data.

    .. grid-item-card::
        :link: resources.html

        :octicon:`book;1em;sd-text-info`  Resources
        ^^^^^^^^^^^
        Here are some other resources and best practices for creating linked data on the web.

    .. grid-item-card::
        :link: examples.html

        :octicon:`pencil;1em;sd-text-info`  Examples
        ^^^^^^^^
        Here are some examples that demonstrate basic usage of the ontology
