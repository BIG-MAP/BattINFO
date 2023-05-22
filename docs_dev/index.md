# BattINFO 

[![BattINFO Github](https://badgen.net/badge/icon/github?icon=github&label)](https://github.com/BIG-MAP/BattINFO)   
[**About**](./about.md)  
[**Contribute**](./contribute.md)


The battery Interface ontology is a digital resource to support interoperability of battery data.   

BattINFO consists of a list of entities representing concepts used in batteries and electrochemistry. Each entity has a unique identifier (IRI) and is annotated with additional information, such as its preferred name ("prefLabel"), alternative names, definition, references, etc. In addition, the entities are connected via links that make explicit the relation between them, e.g. an ElectrochemicalCell --hasPart--> PositiveElectrode.

As users link their resources to BattINFO entities, they are effectively describing their resource using a common vocabulary. If the "Corriente" column in a tabular Dataset A, and the "Current" column in a tabular Dataset B, are both connected to the "Current" entity in BattINFO, then users have made explicit that both columns report the same quantity, enven if these quantities are named in different language. 

The same applies to documents, persons, organizations, equipment, samples... anything that has a unique identifier, and is linked to the common vocabulary described in BattINFO, becomes part of an ecosystem of Findable resources.

about  
contribute

## List of Entities
[**Batteries**](./batteries.md)   
[**Battery Quantities**](./batteryquantties.md)  
[**Electrochemistry**](./electrochemistry.md)  
[**Electrochemical Quantities**](./electrochemicalquantities.md)

### To do
* fix issue with finding the altLabels using SPARQL
* Deploy to HTML and beautify using Bootstrap/Tailwind
* Ancor terms