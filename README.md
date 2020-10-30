[![CI tests](https://github.com/emmo-repo/domain-crystallography/workflows/CI%20tests/badge.svg)](https://github.com/emmo-repo/domain-crystallography/actions/)


domain-batteryInterface
======================
A battery interface domain ontology based on [EMMO][1]. It is implemented as a formal language.


Status
------
- [x] Proposal
- [ ] accepted, under development
- [ ] official

This domain ontology is work-in-progress (WIP), it will be submitted to the
 EMMC for approval once mature for initial testing.

* Application submitted: TBD
* Application accepted on: TBD


Imported Ontologies
-------------------
This ontology builds on top of EMMO. See the following table for version
compatibilies:

| Imported Ontologies | Version           |
| ------------------- | ----------------- |
| EMMO                | 1.0.0-alpha2      |


Obtaining domain-batteryInterface
--------------------------------
This ontology build on EMMO-1.0.0-alpha2. The correct path to 
the inferred verion 'emmo-inferred' is specified in the catalog file, catalog-v001.xml.

The domain ontology is obtained with:
    git clone git@github.com:BIG-MAP-ontologies/domain-batteryInterface.git

When opening batteryInterface.owl in Protege, the correct version of emmo-inferred will
be downloaded and imported.

In EMMO-python correct import is obatined with 
   get_ontology('batteryInterface.owl).load(url_from_catalog=True)


Attributions and credits
------------------------

### Contributors
- Francesca Lønstad Bleken, SINTEF
- Jesper Friis, SINTEF
- Simon Clark, SINTEF
- To be added!

### Projects
- [BigMap](http://www.big-map.eu/);
  Grant Agreement No: 957189
  <img src="bigmap.png" width="30">


License
-------
The battery Interface domain ontology is released under the [Creative
Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/legalcode) license (CC BY 4.0).


[1]: https://github.com/emmo-repo/EMMO
