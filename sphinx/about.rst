About the Battery Ontology
==========================================

The EMMO Battery Domain Ontology is a semantic resource for the terms and relations needed to describe things, processes, and data in the battery domain. It can be used to **generate linked data** for the Semantic Web, **comply with the FAIR data guidelines**, support **interoperaility of data** among different systems, and more!

The Battery Ontology is intended to support researchers, engineers, and developers within the electrochemical
communitiy with activities like:

-  Incorporating consistent and standardized information into their modeling and simulation activities.
-  Enhancing data interoperability between modeling tools, databases, and platforms.
-  Supporting research projects that require precise and standardized electrochemical knowledge representation.
-  Building applications, databases, or knowledge graphs that leverage EMMO and require electrochemical information.
-  Generating linked data in the semantic web.
-  Complying with `FAIR data guidelines <FAIR.md>`__.

Key features of the ontology
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Persistent machine-readable identifiers
---------------------------------------

This ontology assigns persistent machine-readable identifiers (called URIs or IRIs) to concepts from the electrochemistry domain. These identifiers can be resolved to point to human-readable documentation for the term or machine-readable ontology files. Persistent and unique identifiers facilitate data exchange and interoperability among various tools and systems by ensuring consistent nomenclature and providing access to context about the term. 

Standardized Nomenclature
-------------------------

The ontology builds on standardized nomenclature for electrochemistry, relying on recognized authorities. This consistency in nomenclature enhances collaboration and data sharing. In order of precedence, this includes: 

#. `Public IEC/ISO standard vocabulary <https://www.electropedia.org/>`__ The IEC is the the world’s leading organization that prepares and publishes International Standards for all electrical, electronic and related technologies.
#. `IUPAC Goldbook <https://iupac.org/what-we-do/nomenclature/>`__. IUPAC is the universally-recognized authority on chemical nomenclature and terminology.
#. Pre-eminent domain textbooks (e.g. `Bard <https://www.wiley.com/en-kr/Electrochemical+Methods:+Fundamentals+and+Applications,+2nd+Edition-p-9780471043720>`__, `Newman <https://www.wiley.com/en-no/Electrochemical+Systems,+4th+Edition-p->`__, etc.)
#. Discussions with leading figures in electrochemical research

Through a set of term annotations, the ontology also provides links to equivalent terms in other digital knowledge bases, including:

#. `DBpedia <https://www.dbpedia.org/>`__
#. `WikiData <https://www.wikidata.org/>`__
#. `Wikipedia <https://www.wikipedia.org/>`__

Structure and Integration with EMMO
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Electrochemistry Ontology is an official domain of the EMMO. This allows users to benefit from a well-developed and logically consistent framework as well as interoperability with other EMMO domains. For example, the Electrochemistry Ontology also imports other EMMO domains: - `Chemical Substance Domain Ontology <https://github.com/emmo-repo/domain-chemical-substance>`__: provides material annotations for electrochemical (meta)data.

The import structure is summarized in the following table:

.. list-table::
   :header-rows: 1

   * - **Imported Ontologies**
     - **Version**
   * - EMMO
     - 1.0.0-beta5
   * - chemical-substance
     - 0.2.0-alpha 

The onotlogy exists in two forms: (i) the asserted source files and (ii) the pre-inferred version. 

The asserted source consists of two files: - ``battery.ttl``: describes terms and object properties for the electrochemistry domain. - ``batteryquantities.ttl``: describes the quantities related to the electrochemistry domain. It is encapsulated to allow it to be imported by other EMMO domains without needing to import the entire ontology.

The pre-inferred ontology runs the reasoner on the source files and their imports and complies them into a `pre-inferred ontology file <inferred_version/battery-inferred.ttl>`__. This provides a simpler reference for users of the ontology and removes the barrier of needed to run the reasoner themselves. 

Acknowledgements
~~~~~~~~~~~~~~~~

This project has received support from European Union research and innovation programs, under grant agreement numbers:

-  957189 - `BIG-MAP <http://www.big-map.eu/>`__

License
-------

The Battery Interface Domain Ontology is released under the `Creative Commons Attribution 4.0 International <https://creativecommons.org/licenses/by/4.0/legalcode>`__ license (CC BY 4.0).
