# Contributing to BattINFO

There are two ways you can contribute to BattINFO.

## Suggest minor changes on existing elements

Create a [Feature request in a Github Issue](https://docs.github.com/en/issues/tracking-your-work-with-issues/creating-an-issue) to suggest edits to names, defintions, references on existing classes and properties.

## Propose additions/deletion of elements

> **_NOTE:_**  We recommend contacting some of BattINFO contributors in advance to discuss which additions deletions you wish to make.  

We recoommend using the [forking workflow](https://www.atlassian.com/git/tutorials/comparing-workflows/forking-workflow) to contribute additions/deletions. Fork this repository, clone the fork on you local PC, create your branch based on the existing ```dev``` branch (e.g. ```dev_john_doe```) and work on the editions in you local copy. You can edit ontologes in two main ways. One is programmatically, using for instance [EMMOntoPy](https://github.com/emmo-repo/EMMOntoPy). The second and more common is using the interface provided by the Protege software. In case of the latter, [install Protege](https://protege.stanford.edu/) and use it to open the ontology file you wish to edit. Before adding elements, ensure Protege is configured to create IRIs in the right format:  

* Open Protégé
* Go to File/Open and load the ontology file you wish to modify
* Go to File/Preferences and there go to the New Entities Tab
* Ensure you have configured the preferences with the correct IRI prefixes.
* Once you have made your changes, commit them to your fork and [create a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request).
* We will merge the request after assessing it.
