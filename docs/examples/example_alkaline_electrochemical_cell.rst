Alkaline Electrochemical Cell
=============================

This example, let's describe an instance of a simple alkaline electrochemical cell. 

.. hint::

   In this ontology, an ``ElectrochemicalCell`` is simply a combination of components in a holistic arrangement (i.e. two electrodes in contact with an electrolyte). Adding a case and terminals to make it a functional device makes it a ``BatteryCell`` described in the battery domain ontology.

The JSON-LD description of the material is given below:

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