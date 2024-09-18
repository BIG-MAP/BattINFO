Aqueous KOH Electrolyte
=======================

This example, let's describe an instance of some aqueous potassium hydroxide (KOH) electrolyte with some properties. The JSON-LD description of the material is given below:

.. tab-set::

   .. tab-item:: JSON

      .. code-block:: json
         :linenos:

         {
            "@context": "https://raw.githubusercontent.com/emmo-repo/domain-electrochemistry/master/context.json",
            "@type": "Electrolyte",
            "hasSolvent": {
               "@type": "Water"
            },
            "hasSolute": {
               "@type": "PotassiumHydroxide",
               "hasProperty": {
                     "@type": ["AmountConcentration", "ModelledProperty"],
                     "hasNumericalPart": {
                        "@type": "Real",
                        "hasNumericalValue": 7
                     },
                     "hasMeasurementUnit": "emmo:MolePerLitre"
               }
            },
            "hasProperty": [
               {
                     "@type": ["Density", "MeasuredProperty"],
                     "hasNumericalPart": {
                        "@type": "Real",
                        "hasNumericalValue": 1.289
                     },
                     "hasMeasurementUnit": "emmo:KilogramPerLitre"
               },
               {
                     "@type": ["IonicConductivity", "MeasuredProperty"],
                     "hasNumericalPart": {
                        "@type": "Real",
                        "hasNumericalValue": 65
                     },
                     "hasMeasurementUnit": "emmo:SiemensPerCentiMetre"
               }
            ]
         }

   .. tab-item:: JSON-LD Playground

      .. raw:: html
         
         <div style="position: relative; padding-top: 56.25%; height: 0;">
            <iframe src="https://json-ld.org/playground/#startTab=tab-table&json-ld=%7B%22%40context%22%3A%22https%3A%2F%2Fraw.githubusercontent.com%2Femmo-repo%2Fdomain-electrochemistry%2Fmaster%2Fcontext.json%22%2C%22%40type%22%3A%22Electrolyte%22%2C%22hasSolvent%22%3A%7B%22%40type%22%3A%22Water%22%7D%2C%22hasSolute%22%3A%7B%22%40type%22%3A%22PotassiumHydroxide%22%2C%22hasProperty%22%3A%7B%22%40type%22%3A%5B%22AmountConcentration%22%2C%22ModelledProperty%22%5D%2C%22hasNumericalPart%22%3A%7B%22%40type%22%3A%22Real%22%2C%22hasNumericalValue%22%3A7%7D%2C%22hasMeasurementUnit%22%3A%22emmo%3AMolePerLitre%22%7D%7D%2C%22hasProperty%22%3A%5B%7B%22%40type%22%3A%5B%22Density%22%2C%22MeasuredProperty%22%5D%2C%22hasNumericalPart%22%3A%7B%22%40type%22%3A%22Real%22%2C%22hasNumericalValue%22%3A1.289%7D%2C%22hasMeasurementUnit%22%3A%22emmo%3AKilogramPerLitre%22%7D%2C%7B%22%40type%22%3A%5B%22IonicConductivity%22%2C%22MeasuredProperty%22%5D%2C%22hasNumericalPart%22%3A%7B%22%40type%22%3A%22Real%22%2C%22hasNumericalValue%22%3A65%7D%2C%22hasMeasurementUnit%22%3A%22emmo%3ASiemensPerCentiMetre%22%7D%5D%7D" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" frameborder="0" allowfullscreen></iframe>
         </div>

This example highlights a few things:

#. **EMMO distinguishes properties according to how they were determined.** In this example, a ``ConventionalProperty`` is a property whose value is assigned by convention (e.g. from a technical specification sheet, handbook, etc.). EMMO also provides terms for ``MeasuredProperty`` for properties which were actually determined by some measurement and ``ModelledProperty`` for properties that were obtained from some model. 

#. **EMMO has a specific way of expressing quantitative properties.** As shown in the example, a quantitative property has a ``@type`` that describes what kind of property it is, ``hasNumericalPart`` describes the value, and ``hasMeasurementUnit`` defines the unit. Please adhere to this format when expressing quantities in your linked data. 

#. **We can re-use terms from common vocabularies like schema.org.** One of the core principles of linked data is to re-use existing vocabularies when possible. The schema.org vocabulary was developed to support internet search engines and contains terms for things that people often search for (e.g. people, organizations, products, etc.) In this case, we can re-use schema.org terms to describe the manufacturer and product.  

