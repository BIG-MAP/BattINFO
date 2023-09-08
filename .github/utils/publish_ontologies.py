#!/usr/bin/env python3
"""Publish ontologies to GitHub Pages.

Optional environment variables:
- PUBLISH_DOCS_DIR (default: site)
- PUBLISH_ONTOLOGIES_DIR (default: ontology)

"""
from contextlib import redirect_stderr
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Optional
from urllib.error import HTTPError

# Remove the print statement concerning 'owlready2_optimized' when importing Owlready2
# (which is imported also in EMMOntoPy).
with open(os.devnull, "w", encoding="utf8") as handle:
    with redirect_stderr(handle):
        from ontopy import get_ontology


class VersionIRI(str):
    """A versionIRI string.
    
    The structure of the versionIRI is divided up as follows:

        https://<domain>/<path>/<version>/<name>/<filename>

    Each of the parts is accessible as an attribute of the string.
    Note, the last part of the path is the "top name" of the ontology.

    Attributes:
        domain (str): The domain of the versionIRI, e.g., 'big-map.github.io'.
        path (str): The path of the versionIRI, e.g., 'BattINFO/ontology/battinfo'.
        top_name (str): The top name of the versionIRI, e.g., 'battinfo'.
            This is the last part of the path.
        version (str): The version of the versionIRI, e.g., '0.1.0'.
        name (str): The name of the versionIRI, e.g., 'battinfo'.
            Can be omitted in the versionIRI.
        filename (str): The filename of the versionIRI, e.g., 'battinfo.ttl'.
            Can be omitted in the versionIRI.

    """

    _VERSION_IRI_REGEX = re.compile(
        r"https?://(?P<domain>[a-zA-Z._-]+)/(?P<path>[a-zA-Z_-]+(/[a-zA-Z_-]+)*)"
        r"/(?P<version>[0-9a-zA-Z._-]+)(/(?P<name>[a-zA-Z_-]+))?(/(?P<filename>[a-zA-Z_.-]+))?"
    )
    
    def __init__(self, version_iri: str) -> None:
        match = self._VERSION_IRI_REGEX.fullmatch(version_iri)
        if match is None:
            raise ValueError(f"Could not parse versionIRI {version_iri!r}")
        domain, path, version, name, filename = match.groups()
        self._domain = domain
        self._path = path
        self._top_name = path.rsplit("/", 1)[-1]
        self._version = version
        self._name = name if name else None
        self._filename = filename if filename else None

    @property
    def domain(self) -> str:
        """Return the domain of the versionIRI."""
        return self._domain

    @property
    def path(self) -> str:
        """Return the path of the versionIRI."""
        return self._path

    @property
    def top_name(self) -> str:
        """Return the top name of the versionIRI."""
        return self._top_name

    @property
    def version(self) -> str:
        """Return the version of the versionIRI."""
        return self._version

    @property
    def name(self) -> Optional[str]:
        """Return the name of the versionIRI."""
        return self._name

    @property
    def filename(self) -> Optional[str]:
        """Return the filename of the versionIRI."""
        return self._filename


def main() -> None:
    """Main function for publishing ontologies.

    Required global variables:
        - PUBLISH_DOCS_DIR: The directory in which the documentation is built.
        - PUBLISH_DIR: The directory in which the ontologies are published (the versionIRI
          folder structure will be appended to this folder).
        - ROOT_DIR: The root directory of the repository.

    Outline:
        1. Find all local ontologies.
        2. For each ontology:
           1. Load the ontology.
           2. Extract the versionIRI.
           3. Create the versionIRI folder structure in `PUBLISH_DOCS_DIR / PUBLISH_DIR`.
           4. Copy the ontology and catalog file to the versionIRI folder structure.

    """
    publish_root_dir = PUBLISH_DOCS_DIR / PUBLISH_DIR

    local_ontologies = list(ROOT_DIR.glob("*.ttl"))

    catalog_file = sorted(ROOT_DIR.glob("catalog-*.xml"), reverse=True)[0]

    print("Publishing ontologies:", flush=True)
    for ontology_file in local_ontologies:
        print(f"  * {ontology_file.name}", flush=True)
        ontology = get_ontology(str(ontology_file))
        try:
            ontology.load()
        except HTTPError:
            pass

        version_iri = VersionIRI(ontology.get_version(as_iri=True))

        # Create the versionIRI folder structure.
        relative_destination_dir = (
            Path() / version_iri.top_name / version_iri.version / version_iri.name
            if version_iri.name
            else Path() / version_iri.top_name / version_iri.version
        )
        (publish_root_dir / relative_destination_dir).mkdir(parents=True, exist_ok=True)

        # Copy the ontology and catalog file to the versionIRI folder structure.
        shutil.copyfile(
            src=ontology_file,
            dst=publish_root_dir / relative_destination_dir / ontology_file.name,
        )
        shutil.copyfile(
            src=catalog_file,
            dst=publish_root_dir / relative_destination_dir / catalog_file.name,
        )


if __name__ == "__main__":
    ROOT_DIR = Path(__file__).resolve().parent.parent.parent
    PUBLISH_DOCS_DIR = ROOT_DIR / os.environ.get("PUBLISH_DOCS_DIR", "site")
    PUBLISH_DIR = Path(os.environ.get("PUBLISH_ONTOLOGIES_DIR", "ontology"))

    try:
        main()
    except Exception as exc:
        sys.exit(str(exc))
