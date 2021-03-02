# Introduction

Battery development is one of the most important and intensely pursued technical research topics in the world today.
From personal electronics to electric mobility to renewable energy storage, batteries are essential to progress.
The search for better batteries is supported by a host of databases, methods, models, publications, and presentations.
How can we distil this deluge of data into knowledge and translate that knowledge into action?

The answer must rely in some part on artificial intelligence (AI).
The breadth of fields necessary to completely describe of battery performance, characterization, and simulation combined with the depth of research being generated in those fields is simply too great for any single person (or even group of people) to manage.
However, the challenge is that the wealth of battery data that exists is formatted to be read, understood, and learned by humans, not machines.
The field needs a tool to formalize the current state of knowledge about battery interfaces that is both human- and machine-readable.

The [Battery Interface Ontology (BattINFO)][BattINFO] is a domain ontology for batteries and their interfaces.
It is developed with the goal of creating a formalized description of battery cells to support the interoperability of battery data and support applications of artificial intelligence in battery research.

BattINFO builds upon long-standing and widely accepted principles of electrochemistry as described in preeminent texts such as Electrochemical Systems by John Newman and Karen E. Thomas-Alyea [1], Electrochemical Methods: Fundamentals and Applications by Allen J. Bard and Larry R. Faulkner [2], and Handbook of Batteries by David Linden and Thomas B. Reddy [3], among other seminal sources [4], [5].
The terminology adheres as far as possible to the recommendations and definitions contained in the Compendium of Chemical Terminology (also known as the "Gold Book") from the International Union of Pure and Applied Chemistry (IUPAC) [6] together with IUPAC supplements on electrochemical terminology [7] and recommendations from the Electrochemical Society (ECS) on nomenclature and standards.
Places where conflicts exist between sources are noted for further discussion and resolution within the electrochemical community.

BattINFO employs the [European Materials and Modelling Ontology (EMMO)][EMMO] as a top-level ontology.
EMMO aims at the development of a standard representational ontology framework based on current materials modelling and characterization of knowledge.
EMMO starts from the very basic scientific fundamentals and grows to encompass a complex and wide field of knowledge, however it is still functional and clear.
This makes it ideal to support the development of BattINFO as an EMMO domain ontology.

The purpose of this report is to lay the groundwork for the development of BattINFO in the [BIG-MAP][BIG-MAP] project.

## Availability and license

The Battery Interface Domain Ontology is available from the github repository [https://github.com/BIG-MAP/BattINFO][BattINFO].

It is released under the [Creative Commons Attribution 4.0 International license (CC BY 4.0)][CC-BY-4.0].

## References

1. J. Newman and K. E. Thmoas-Alyea, Electrochemical Systems, 3rd ed. Hoboken, New Jersey: John Wiley & Sons, 2004.
2. A. J. Bard and L. R. Faulkner, ELECTROCHEMICAL METHODS: Fundamentals and applications. 2001.
3. D. Linden and T. Reddy, Handbook of Batteries. 2002.
4. P. Atkins and J. De Paula, Atkins' Physical Chemistry, 8th Ed. New York: W.H. Freeman and Company, 2006.
5. M. Pourbaix, Atlas of Electrochemical Equilibria in Aqueous Solutions, Second. Houston, Texas: National Association of Corrosion Engineers, 1974.
6. IUPAC, Compendium of Chemical Terminology, 2nd (the ". Oxford: Blackwell Scientific Publications, 2014.
7. J. M. Pingarrón et al., Terminology of electrochemical methods of analysis (IUPAC Recommendations 2019), Pure Appl. Chem., vol. 92, no. 4, pp. 641-694, 2020.

[BattINFO]: https://github.com/BIG-MAP/BattINFO
[EMMO]: https://github.com/emmo-repo/EMMO/
[BIG-MAP]: http://www.big-map.eu/
[CC-BY-4.0]: https://creativecommons.org/licenses/by/4.0/legalcode
