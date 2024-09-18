Cyclic Voltammetry Data
=======================

This example, let's describe an instance of some data describing an Nyquist plot from an EIS measurement. The JSON-LD description of the material is given below:

.. tab-set::

   .. tab-item:: Raw Data

      Here is a sample of the raw data. The full dataset is available `here <https://raw.githubusercontent.com/emmo-repo/domain-electrochemistry/master/sphinx/assets/data/example-cyclic-voltammetry.csv>`__.

      .. code-block:: text

         Z_real (Ohm),        Z_imag (Ohm) 
         0.697447795823666,   0.0594427244582042 
         0.703016241299304,   0.02786377708978327 
         0.7122969837587008,  0.0018575851393187737 
         0.7178654292343388, -0.022291021671826727 
         0.7290023201856148, -0.05015479876161011 
         0.7549883990719257, -0.07987616099071215 
         0.7735498839907193, -0.10030959752321988 
         0.8013921113689095, -0.11888544891640884 
         0.8348027842227379, -0.13003095975232204 
         ...

   .. tab-item:: JSON

      .. code-block:: json
         :linenos:

         {
            "@context": "https://raw.githubusercontent.com/emmo-repo/domain-electrochemistry/master/context.json",
            "@type": "MeasurementResult",
            "csvw:url": "https://archive.big-map.eu/records/24mdd-z2x02/files/LNO%20CV.csv",
            "dc:title": "Example EIS Nyquist Plot Data",
            "dcat:keyword": ["EIS", "Nyquist"],
            "dc:license": "BIG-MAP Archive License",
            "dc:modified": {"@value": "2024-01-29", "@type": "xsd:date"},
            "dc:source": "http://dx.doi.org/10.1149/2.0321816jes",
            "dc:contributor": {
               "@id": "https://orcid.org/0000-0002-8758-6109",
               "schema:name": "Simon Clark"
            },
            "@reverse": {
               "hasOutput": {
               "@type": "ElectrochemicalImpedanceSpectroscopy"
               }
            },
            "csvw:tableSchema": {
               "csvw:columns": [{
                  "csvw:name": "real",
                  "csvw:titles": "Z_real (Ohm)",
                  "csvw:propertyUrl": {
                     "@type": ["ElectricImpedance", "Real"]
                  },
                  "hasMeasurementUnit": "emmo:Ohm",
                  "csvw:datatype": "number",
                  "csvw:required": true
               }, {
                  "csvw:name": "imaginary",
                  "csvw:titles": "Z_imag (Ohm)",
                  "csvw:propertyUrl": {
                     "@type": ["ElectricImpedance", "Imaginary"]
                  },
                  "hasMeasurementUnit": "emmo:Ohm",
                  "csvw:datatype": "number"
               }],
               "csvw:primaryKey": "real"
               }
         }

   .. tab-item:: JSON-LD Playground

      .. raw:: html
         
         <div style="position: relative; padding-top: 56.25%; height: 0;">
            <iframe src="https://json-ld.org/playground/#startTab=tab-table&json-ld=%7B%22%40context%22%3A%22https%3A%2F%2Fraw.githubusercontent.com%2Femmo-repo%2Fdomain-electrochemistry%2Fmaster%2Fcontext.json%22%2C%22%40type%22%3A%22MeasurementResult%22%2C%22csvw%3Aurl%22%3A%22https%3A%2F%2Farchive.big-map.eu%2Frecords%2F24mdd-z2x02%2Ffiles%2FLNO%2520CV.csv%22%2C%22dc%3Atitle%22%3A%22Example%20EIS%20Nyquist%20Plot%20Data%22%2C%22dcat%3Akeyword%22%3A%5B%22EIS%22%2C%22Nyquist%22%5D%2C%22dc%3Alicense%22%3A%22BIG-MAP%20Archive%20License%22%2C%22dc%3Amodified%22%3A%7B%22%40value%22%3A%222024-01-29%22%2C%22%40type%22%3A%22xsd%3Adate%22%7D%2C%22dc%3Asource%22%3A%22http%3A%2F%2Fdx.doi.org%2F10.1149%2F2.0321816jes%22%2C%22dc%3Acontributor%22%3A%7B%22%40id%22%3A%22https%3A%2F%2Forcid.org%2F0000-0002-8758-6109%22%2C%22schema%3Aname%22%3A%22Simon%20Clark%22%7D%2C%22%40reverse%22%3A%7B%22hasOutput%22%3A%7B%22%40type%22%3A%22ElectrochemicalImpedanceSpectroscopy%22%7D%7D%2C%22csvw%3AtableSchema%22%3A%7B%22csvw%3Acolumns%22%3A%5B%7B%22csvw%3Aname%22%3A%22real%22%2C%22csvw%3Atitles%22%3A%22Z_real%20(Ohm)%22%2C%22csvw%3ApropertyUrl%22%3A%7B%22%40type%22%3A%5B%22ElectricImpedance%22%2C%22Real%22%5D%7D%2C%22hasMeasurementUnit%22%3A%22emmo%3AOhm%22%2C%22csvw%3Adatatype%22%3A%22number%22%2C%22csvw%3Arequired%22%3Atrue%7D%2C%7B%22csvw%3Aname%22%3A%22imaginary%22%2C%22csvw%3Atitles%22%3A%22Z_imag%20(Ohm)%22%2C%22csvw%3ApropertyUrl%22%3A%7B%22%40type%22%3A%5B%22ElectricImpedance%22%2C%22Imaginary%22%5D%7D%2C%22hasMeasurementUnit%22%3A%22emmo%3AOhm%22%2C%22csvw%3Adatatype%22%3A%22number%22%7D%5D%2C%22csvw%3AprimaryKey%22%3A%22real%22%7D%7D" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" frameborder="0" allowfullscreen></iframe>
         </div>

This example highlights a few things:

#. **EMMO distinguishes properties according to how they were determined.** In this example, a ``ConventionalProperty`` is a property whose value is assigned by convention (e.g. from a technical specification sheet, handbook, etc.). EMMO also provides terms for ``MeasuredProperty`` for properties which were actually determined by some measurement and ``ModelledProperty`` for properties that were obtained from some model. 

#. **EMMO has a specific way of expressing quantitative properties.** As shown in the example, a quantitative property has a ``@type`` that describes what kind of property it is, ``hasNumericalPart`` describes the value, and ``hasMeasurementUnit`` defines the unit. Please adhere to this format when expressing quantities in your linked data. 

#. **We can re-use terms from common vocabularies like schema.org.** One of the core principles of linked data is to re-use existing vocabularies when possible. The schema.org vocabulary was developed to support internet search engines and contains terms for things that people often search for (e.g. people, organizations, products, etc.) In this case, we can re-use schema.org terms to describe the manufacturer and product.  

