# Publishing documentation and ontologies

This document is meant for developers who wish to understand how the publishing of documentation and ontologies works (and is intended).

## Publishing documentation

The documentation is published via [GitHub Pages](https://pages.github.com/).

In the lifetime of the repository, the documentation has been built and published in two ways:

1. Building the documentation using [EMMOntoPy](https://github.com/emmo-repo/EMMOntoPy) and then pushing the built documentation to the `gh-pages` branch of the repository.
2. Building the documentation from the Python script [`md_to_html.py`](./md_to_html.py) converting MarkDown files in the `docs` folder to HTML and then then committing the changes before pushing back to the `master` branch.

The (new) intended publication method is a combination of the two.
The build process will be an extension of the second approach, while the documentation will be published to the `gh-pages` branch of the repository.

When building the documentation, not only are any MarkDown files found in the `docs` folder (excluding those found in the `assets`, `css`, and `scripts` folders) converted to HTML, but the static files meant to be utilized in the documentation (i.e., the `assets` and `css` folders) are also copied to a target, dedicated folder.
This is all done by the Python script [`build.py`](./build.py) script.

The contents of the dedicated folder is then merged into the `gh-pages` branch of the repository, publishing the documentation.

By merging in the contents of the dedicated folder, the `gh-pages` branch will contain and preserve any old ontology versions that shouldn't be removed, while updating the documentation and adding any new ontology versions.

### Building the documentation (locally)

To build the documentation locally, run the following command from the root of the repository:

```shell
python docs/scripts/build.py site
```

Now you can open the `index.html` file in the `site` folder to view the documentation.

## Publishing ontologies

Publishing the ontologies means copying the Turtle (`.ttl`) files into an appropriate sub-folder of the `ontology` folder in the `gh-pages` branch of the repository, along with a copy of the `catalog-v001.xml` file.
This is done by the [`publish_ontologies.py`](../../.github/utils/publish_ontologies.py) script.

To determine the relative path to the sub-folder, the script uses the `owl:versionIRI` value to determine the version of the ontology.
Then it creates the path `ontology/<ontology_top_name>/<version>/` and copies the Turtle files into it.
If the ontology has a specific "sub"-name, e.g., `batteryquantities`, then the path will be `ontology/<ontology_top_name>/<version>/<sub_name>/`.

For the core BattINFO ontology, the path should be `ontology/BattINFO/<version>/`.

### Publishing ontologies (locally)

To publish the ontologies locally, run the following command from the root of the repository:

```shell
python .github/utils/publish_ontologies.py
```

If one wishes to control the publication location further, one can set environment variables:

| Environment variable | Description | Default value |
| --- | --- | --- |
| `PUBLISH_DOCS_DIR` | The path to the directory where the documentation should be published. This can be relative to the root of the repository or an absolute path. | `site` |
| `PUBLISH_ONTOLOGIES_DIR` | The path to the directory where the ontologies should be published. This **must** be a relative path, relative to `PUBLISH_DOCS_DIR`. | `ontology` |
