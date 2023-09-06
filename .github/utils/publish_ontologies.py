#!/usr/bin/env python3
"""Publish ontologies to GitHub Pages."""
from contextlib import redirect_stderr
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.error import HTTPError

# Remove the print statement concerning 'owlready2_optimized' when importing owlready2
# (which is imported also in emmo).
with open(os.devnull, "w", encoding="utf8") as handle:
    with redirect_stderr(handle):
        from ontopy import get_ontology


REQUIRED_ENVIRONMENT_VARIABLES = (
    "ONTODOC_DIR", "TMP_DIR", "PAGES_DIR", "PUBLISH_ONTOLOGIES_DIR"
)

class EnvironmentVariableNotFound(Exception):
    """A required environment variable was not found to be set."""


def check_environment() -> None:
    """Check the environment has the needed variables."""
    missing_variables = []
    for required_env_var in REQUIRED_ENVIRONMENT_VARIABLES:
        if required_env_var not in os.environ:
            missing_variables.append(required_env_var)

    if missing_variables:
        raise EnvironmentVariableNotFound(
            "The following required environment variable(s) was not found to be set "
            f"in the environment: {', '.join(missing_variables)}."
        )


def main() -> None:
    """Main function for publishing ontologies.

    Required global variables:
    - PAGES_DIR
    - ROOT_DIR
    - VERSION_IRI_REGEX
    - PUBLISH_URL
    - PUBLISH_DIR

    Outline:
    - Walk through all ontologies.
    - Create dict with versions.
    - Determine URI/IRI based on ontology name and version.
    - Generate `ontology` folder with the determined file structure.

    """
    absolute_publish_dir = PAGES_DIR / PUBLISH_DIR

    local_ontologies = list(ROOT_DIR.glob("*.ttl"))

    catalog_file = sorted(ROOT_DIR.glob("catalog-*.xml"), reverse=True)[0]

    print("Publishing ontologies:")
    for ontology_file in local_ontologies:
        print(f"  * {ontology_file.name}")
        ontology = get_ontology(str(ontology_file))
        try:
            ontology.load()
        except HTTPError:
            pass
        version_iri = ontology.get_version(as_iri=True)
        version_iri_match = VERSION_IRI_REGEX.fullmatch(version_iri)
        if version_iri_match is None:
            raise ValueError(f"Could not retrieve versionIRI properly from {ontology_file.name!r}")

        version_iri_parts = version_iri_match.groupdict()
        version_iri_parts["top_name"] = version_iri_parts["path"].rsplit("/", 1)[-1]

        relative_destination_dir = (
            Path() / version_iri_parts["top_name"] / version_iri_parts["version"] / version_iri_parts["name"]
            if version_iri_parts["name"]
            else Path() / version_iri_parts["top_name"] / version_iri_parts["version"]
        )
        (absolute_publish_dir / relative_destination_dir).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            src=ontology_file,
            dst=absolute_publish_dir / relative_destination_dir / ontology_file.name,
        )
        shutil.copyfile(
            src=catalog_file,
            dst=absolute_publish_dir / relative_destination_dir / catalog_file.name,
        )


if __name__ == "__main__":
    try:
        check_environment()
    except Exception as exc:
        sys.exit(str(exc))

    ROOT_DIR = Path(__file__).resolve().parent.parent.parent
    PAGES_DIR = ROOT_DIR / os.environ["ONTODOC_DIR"] / os.environ["TMP_DIR"] / os.environ["PAGES_DIR"]
    PUBLISH_DIR = Path(os.environ["PUBLISH_ONTOLOGIES_DIR"])
    PUBLISH_URL = f"https://big-map.github.io/BattINFO/{PUBLISH_DIR}"
    VERSION_IRI_REGEX = re.compile(
        r"https?://(?P<domain>[a-zA-Z._-]+)/(?P<path>[a-zA-Z_-]+(/[a-zA-Z_-]+)*)"
        r"/(?P<version>[0-9a-zA-Z._-]+)(/(?P<name>[a-zA-Z_-]+))?(/(?P<filename>[a-zA-Z_.-]+))?"
    )

    try:
        main()
    except Exception as exc:
        sys.exit(str(exc))
