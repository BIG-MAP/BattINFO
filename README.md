<!-- markdownlint-disable MD033 -->

# Battery Interface Ontology (BattINFO)

Welcome to the Battery Interface Ontology (BattINFO): a semantic resource for describing knowledge about batteries and creating [Linked Data][1]! 

BattINFO is a foundational resource for harmonizing battery knowledge representation and enhancing data interoperability. The primary objective is to provide the necessary tools to create [FAIR (Findable, Accessible, Interoperable, Reusable)][2] battery data that can be integrated into the [Semantic Web][3].

## Usage

The Battery Interface Ontology is aimed at developers, engineers, researchers, and other professionals in the battery domain who would like to:

- Assign meaning to their data in a way that can be understood by both machines and humans;
- Enhance data interoperability between different databases and tools;
- Standardize representation of battery knowledge;
- Enable semantic queries of (meta)data;
- Comply with FAIR data guidelines.

## Key Features

### Persistent Identifiers

This ontology assigns persistent machine-readable identifiers to concepts from the battery domain. These identifiers facilitate data exchange and interoperability for both humans and machines. The ontology uses the w3id.org Permanent Uniform Resource Locator (PURL) service to ensure that the identifiers are robust and permanent. It includes annotations to other sources of information including [DBPedia](https://www.dbpedia.org/) and [Wikidata](https://www.wikidata.org/). 

### Standardized Nomenclature

The ontology builds on standardized nomenclature for batteries, relying on recognized authorities including [IUPAC](https://iupac.org/what-we-do/nomenclature/) and the [IEC](https://www.electropedia.org/). IUPAC is the universally-recognized authority on chemical nomenclature and terminology, and IEC is the the world's leading organization that prepares and publishes International Standards for all electrical, electronic and related technologies. This consistency in naming conventions enhances collaboration and data sharing.

### Integration with the EMMO Universe

BattINFO is defined under the recommendations of the [Elementary Multiperspective Materials Ontology (EMMO)][4]. The EMMO provides a top-level ontology, with a focus on describing knowledge related to the natural sciences and engineering. It hosts a variety of domain ontologies on a wide range of topics including characterization methodology, crystallography, electrochemistry, and more. By defining BattINFO according to the recommendations of the EMMO, we can establish interoperability with all other resources in the EMMO Universe.

### Compliance with W3C Standards and Best Practices

The World Wide Web Consortium (W3C) is the organization responsible for maintaining the standards that form the foundation for the Web. To streamline the exchange and interpretation of Web-based data, they have created a set of standards that form the basis for the Semantic Web: an extension of the World Wide Web that is centered around data and designed to be navigated by machines. The Resource Description Framework (RDF) is one of the cornerstone standards for the Semantic Web that provides a standard model for data exchange. 

BattINFO is defined within these W3C recommendations to allow for easy integration of data into the Semantic Web. Furthermore, we provide examples of data annotation in some of the most common RDF formats like JSON-LD.

## Getting Started

The best way to stay up to date with the latest version of the ontology is to clone this repository.

```console
git clone https://github.com/BIG-MAP/BattINFO.git
```

The BattINFO documentation provides some guidelines on:
- [How to Get Started](https://big-map.github.io/BattINFO/getstarted.html)
- [Tools for Ontology Users and Developers](https://big-map.github.io/BattINFO/tools.html)
- [Examples of the Ontology in Action!](https://big-map.github.io/BattINFO/examples.html)

### Quick Start in Python

In python, the ontology can be handled with the pacakge [EMMOntoPy][2]. This
package can be installed with `pip install emmontopy`.

BattINFO can then be loaded using the following commands:

```python
from ontopy import get_ontology

# Loading from local repository
battinfo = get_ontology('/path/to/BattINFO/battinfo.ttl').load(url_from_catalog=True)

# Loading from web
battinfo = get_ontology('https://raw.githubusercontent.com/BIG-MAP/BattINFO/master/battinfo.ttl').load()
```= get_ontology('https://raw.githubusercontent.com/emmo-repo/domain-battery/master/inferred_version/battery-inferred.ttl').load()
```
## License

The Battery Interface Domain Ontology is released under the [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/legalcode) license (CC BY 4.0).

## Acknowledgements

<img src="sphinx/img/EU_Flag.jpg" alt="EU-Flag" width="100">

This project has received support from European Union research and innovation programs, under grant agreement numbers:

* 957189 - [BIG-MAP](http://www.big-map.eu/) 

[1]: https://www.w3.org/wiki/LinkedData 
[2]: https://www.go-fair.org/fair-principles/
[3]: https://en.wikipedia.org/wiki/Semantic_Web
[4]: https://big-map.github.io/BattINFO/index.html
[5]: https://github.com/emmo-repo/EMMO
[6]: https://www.big-map.eu
