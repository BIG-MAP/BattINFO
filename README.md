<!-- markdownlint-disable MD033 -->

# Battery Interface Ontology (BattINFO)

BattINFO is a domain of the [Elementary Multiperspective Materials Ontology (EMMO)][1], for describing battery systems, materials, methods, and data. Its primary objective is to support the creation of [FAIR](https://www.go-fair.org/fair-principles/), [Linked Data](https://en.wikipedia.org/wiki/Linked_data). This ontology serves as a foundational resource for harmonizing battery knowledge representation, enhancing data interoperability, and accelerating progress in battery research and innovation.

Reference documentation is available [here](https://emmo-repo.github.io/domain-battery/index.html).
 
# Quick Start

Here is some information to help you get started working with the ontology in python and creating you own instances of Linked Data. For more information, please see the [Getting Started](https://emmo-repo.github.io/domain-battery/pages/getstarted.html) and [Examples](https://emmo-repo.github.io/domain-battery/pages/examples.html) section of the documentation. 

## Reference IRIs

The table below contains a quick cheat sheet of IRIs for accessing different files from the ontology
The import structure is summarized in the following table:

| IRI                                        | Description                   |
| ------------------------------------------ | ----------------------------- |
| `https://w3id.org/battinfo`                | Base Asserted Ontology*       |
| `https://w3id.org/battinfo/inferred`       | Base Pre-Inferred Ontology*   |
| `https://w3id.org/battinfo/latest`         | Latest Asserted Ontology*     |
| `https://w3id.org/battinfo/source`         | Source of Asserted Ontology*  |
| `https://w3id.org/battinfo/context`        | Latest JSON-LD Context File   |
| `https://w3id.org/battinfo/{VERSION}`      | Version of Asserted Ontology* |
| `https://w3id.org/battinfo/{VERSION}/...`  | ... follows same logic above  |

*IRI directs to human readable documentation if called from the web browser and to the source .ttl file if called from an application

## Python
There are two common ways to work with the ontology in python: loading the ontology as a graph using [rdflib](https://rdflib.readthedocs.io/en/stable/) or exploring the content of the ontology using [EMMOntoPy](https://github.com/emmo-repo/EMMOntoPy). Examples of both are provided below.

### rdflib
In [rdflib](https://rdflib.readthedocs.io/en/stable/), you can import the ontology as a graph, e.g. to run SPARQL queries:

```python
from rdflib import Graph

# Define the IRI of the ontology
battinfo = "https://w3id.org/battinfo"

# Create an empty graph
g = Graph()

# Load the ontology from the IRI
g.parse(battinfo, format="ttl")

# Print the number of triples in the graph
print(f"Graph has {len(g)} triples.")
```
### EMMOntoPy
In [EMMOntoPy](https://github.com/emmo-repo/EMMOntoPy), you can choose to import the ontology directly from the web:

```python
from ontopy import get_ontology

# Loading from web
battinfo = get_ontology('https://w3id.org/battinfo').load()
```

## Usage

This domain ontology supports the creation of Linked Data in any RDF-supported format. Below is an example using [JSON-LD](https://json-ld.org/) to desecribe a zinc foil electrode with some creator information and properties. Please see the documentation for [more examples](https://emmo-repo.github.io/domain-battery/pages/examples.html). 

```json
{
    "@context": "https://w3id.org/emmo/domain/battery/context",
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
```

## Acknowledgements

<img src="docs/assets/img/EU_Flag.jpg" alt="EU-Flag" width="100">

This project has received support from European Union research and innovation programs, under grant agreement numbers:

* 957189 - [BIG-MAP](http://www.big-map.eu/) 

[1]: https://www.w3.org/wiki/LinkedData 
[2]: https://www.go-fair.org/fair-principles/
[3]: https://en.wikipedia.org/wiki/Semantic_Web
[4]: https://big-map.github.io/BattINFO/index.html
[5]: https://github.com/emmo-repo/EMMO
[6]: https://www.big-map.eu
