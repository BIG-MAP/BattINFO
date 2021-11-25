"""Publish ontologies to GitHub Pages."""
from pathlib import Path
import re
import shutil
import sys
from urllib.error import HTTPError

from ontopy import get_ontology


REPO_DIR = Path(__file__).parent.parent.parent.resolve()
PUBLISH_URL = "https://big-map.github.io/BattINFO/ontology"
VERSION_IRI_REGEX = re.compile(
    r"https?://(?P<domain>[a-zA-Z._-]+)/(?P<path>[a-zA-Z_-]+(/[a-zA-Z_-]+)*)"
    r"/(?P<version>[0-9a-zA-Z._-]+)(/(?P<name>[a-zA-Z_-]+))?"
)

def main() -> None:
    """Main function for publishing ontologies.

    Outline:
    - Walk through all ontologies.
    - Create dict with versions.
    - Determine URI/IRI based on ontology name and version.
    - Generate `ontology` folder with the determined file structure.

    """
    local_ontologies = list(REPO_DIR.glob("*.ttl"))
    documentation_root_dir = REPO_DIR / "publish"
    publish_dir = documentation_root_dir / "ontology"

    publish_dir.mkdir(parents=True, exist_ok=True)

    for ontology_file in local_ontologies:
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

        shutil.copyfile(
            src=ontology_file,
            dst=(
                publish_dir / version_iri_parts["top_name"] / version_iri_parts["version"] / version_iri_parts["name"] / ontology_file.name
                if version_iri_parts["name"]
                else publish_dir / version_iri_parts["top_name"] / version_iri_parts["version"] / ontology_file.name
            ),
        )

        if not version_iri.startswith(PUBLISH_URL):
            # Serve ontologies outside the BIG-MAP domain as part of these ontologies.
            # Change the catalog URI, but not the name, i.e., download from the BIG-MAP
            # domain.
            catalog_file = sorted(REPO_DIR.glob("catalog-*.xml"), reverse=True)[0]
            with open(catalog_file, "r", encoding="utf8") as handle:
                lines = [
                    re.sub(
                        fr"uri=('|\"){ontology_file.name}('|\")",
                        f"uri=\"{PUBLISH_URL}/{version_iri_parts['top_name']}/{version_iri_parts['version']}{'/' + version_iri_parts['name'] if version_iri_parts['name'] else ''}/{ontology_file.name}\"",
                    ) for _ in handle
                ]
            with open(catalog_file, "w", encoding="utf8") as handle:
                handle.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.exit(str(exc))
