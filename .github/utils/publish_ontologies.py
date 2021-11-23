"""Publish ontologies to GitHub Pages."""
from pathlib import Path
from urllib.error import HTTPError
import sys

from ontopy import get_ontology


REPO_DIR = Path(__file__).parent.parent.parent.resolve()


def main() -> None:
    """Main function for publishing ontologies.

    Outline:
    - Walk through all ontologies.
    - Create dict with versions.
    - Determine URI/IRI based on ontology name and version.
    - Generate `ontology` folder with the determined file structure.

    """
    local_ontologies = list(REPO_DIR.glob("*.ttl"))
    publish_dir = REPO_DIR / "publish"

    for ontology_file in local_ontologies:
        ontology = get_ontology(str(ontology_file))
        try:
            ontology.load()
        except HTTPError:
            pass


if __name__ == "__main__":
    sys.exit(main())
