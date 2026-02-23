Zinc Electrode
==============

This example, let's describe an instance of some electrode made by a specific person at a research institute using zinc foil. The electrode has properties that were determined from a combination of a specification sheet and actual measurements. The JSON-LD description of the material is given below:

.. tab-set::

   .. tab-item:: JSON

      .. code-block:: json
         :linenos:

         {
            "@context": "https://raw.githubusercontent.com/emmo-repo/domain-electrochemistry/master/context.json",
            "@type": "Electrode",
            "schema:manufacturer": {
               "@id": "https://www.wikidata.org/wiki/Q3041255",
               "schema:name": "SINTEF"
            },
            "schema:creator": {
               "@id": "https://orcid.org/0000-0002-8758-6109",
               "schema:name": "Simon Clark"
            },
            "hasActiveMaterial": {
               "@type": ["Zinc", "Foil"]
            }, 
            "hasProperty": [
               {
                     "@type": ["SpecificCapacity", "MeasuredProperty"],
                     "hasNumericalPart": {
                        "@type": "Real",
                        "hasNumericalValue": 800
                     },
                     "hasMeasurementUnit": "emmo:MilliAmpereHourPerGram"
               }, 
               {
                     "@type": ["Thickness", "ConventionalProperty"],
                     "hasNumericalPart": {
                        "@type": "Real",
                        "hasNumericalValue": 250
                     },
                     "hasMeasurementUnit": "emmo:MicroMetre"
               }, 
               {
                     "@type": ["Diameter", "MeasuredProperty"],
                     "hasNumericalPart": {
                        "@type": "Real",
                        "hasNumericalValue": 2
                     },
                     "hasMeasurementUnit": "emmo:CentiMetre"
               }, 
               {
                     "@type": ["Mass", "MeasuredProperty"],
                     "hasNumericalPart": {
                        "@type": "Real",
                        "hasNumericalValue": 2.5
                     },
                     "hasMeasurementUnit": "emmo:Gram"
               }
            ]
         }

   .. tab-item:: JSON-LD Playground

      .. raw:: html
         
         <div style="position: relative; padding-top: 56.25%; height: 0;">
            <iframe src="https://json-ld.org/playground/#startTab=tab-canonized&json-ld=%7B%22%40context%22%3A%22https%3A%2F%2Fraw.githubusercontent.com%2Femmo-repo%2Fdomain-electrochemistry%2Fmaster%2Fcontext.json%22%2C%22%40type%22%3A%22Electrode%22%2C%22schema%3Amanufacturer%22%3A%7B%22%40id%22%3A%22https%3A%2F%2Fwww.wikidata.org%2Fwiki%2FQ3041255%22%2C%22schema%3Aname%22%3A%22SINTEF%22%7D%2C%22schema%3Acreator%22%3A%7B%22%40id%22%3A%22https%3A%2F%2Forcid.org%2F0000-0002-8758-6109%22%2C%22schema%3Aname%22%3A%22Simon%20Clark%22%7D%2C%22hasActiveMaterial%22%3A%7B%22%40type%22%3A%5B%22Zinc%22%2C%22Foil%22%5D%7D%2C%22hasProperty%22%3A%5B%7B%22%40type%22%3A%5B%22SpecificCapacity%22%2C%22MeasuredProperty%22%5D%2C%22hasNumericalPart%22%3A%7B%22%40type%22%3A%22Real%22%2C%22hasNumericalValue%22%3A800%7D%2C%22hasMeasurementUnit%22%3A%22emmo%3AMilliAmpereHourPerGram%22%7D%2C%7B%22%40type%22%3A%5B%22Thickness%22%2C%22ConventionalProperty%22%5D%2C%22hasNumericalPart%22%3A%7B%22%40type%22%3A%22Real%22%2C%22hasNumericalValue%22%3A250%7D%2C%22hasMeasurementUnit%22%3A%22emmo%3AMicroMetre%22%7D%2C%7B%22%40type%22%3A%5B%22Diameter%22%2C%22MeasuredProperty%22%5D%2C%22hasNumericalPart%22%3A%7B%22%40type%22%3A%22Real%22%2C%22hasNumericalValue%22%3A2%7D%2C%22hasMeasurementUnit%22%3A%22emmo%3ACentiMetre%22%7D%2C%7B%22%40type%22%3A%5B%22Mass%22%2C%22MeasuredProperty%22%5D%2C%22hasNumericalPart%22%3A%7B%22%40type%22%3A%22Real%22%2C%22hasNumericalValue%22%3A2.5%7D%2C%22hasMeasurementUnit%22%3A%22emmo%3AGram%22%7D%5D%7D" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" frameborder="0" allowfullscreen></iframe>
         </div>

This example highlights a few things:

#. **EMMO distinguishes properties according to how they were determined.** In this example, a ``ConventionalProperty`` is a property whose value is assigned by convention (e.g. from a technical specification sheet, handbook, etc.). EMMO also provides terms for ``MeasuredProperty`` for properties which were actually determined by some measurement and ``ModelledProperty`` for properties that were obtained from some model. 

#. **EMMO has a specific way of expressing quantitative properties.** As shown in the example, a quantitative property has a ``@type`` that describes what kind of property it is, ``hasNumericalPart`` describes the value, and ``hasMeasurementUnit`` defines the unit. Please adhere to this format when expressing quantities in your linked data. 

#. **We can re-use terms from common vocabularies like schema.org.** One of the core principles of linked data is to re-use existing vocabularies when possible. The schema.org vocabulary was developed to support internet search engines and contains terms for things that people often search for (e.g. people, organizations, products, etc.) In this case, we can re-use schema.org terms to describe the manufacturer and product.  

