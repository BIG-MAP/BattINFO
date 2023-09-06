"""Build documentation.

This script builds the documentation using the generated HTML files from the
md_to_html.py script and the CSS and other assets.

Usage: python build.py <output_path>

The output path is the directory where the documentation will be built.
It should be a relative path from the root of the repository written in POSIX style.

Examples:
    python build.py site
    python build.py docs/html

"""
from pathlib import Path
import shutil
import sys

from md_to_html import rendering_workflow

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.resolve()
KNOWN_REPO_FOLDERS = [".git", ".github", "docs"]

STATIC_DOCS_FOLDERS = ["assets", "css"]


class Abort(Exception):
    """Abort execution with 0 exit code."""


def _remove_folder(folder: Path) -> None:
    """Remove a folder recursively."""
    for child in folder.iterdir():
        if child.is_dir():
            _remove_folder(child)
        else:
            child.unlink()
    folder.rmdir()


def build(output_folder: Path) -> None:
    """Build documentation."""
    # Check output folder
    if output_folder.exists():
        if any(output_folder.as_posix().startswith(_) for _ in KNOWN_REPO_FOLDERS):
            print(
                f"Output folder {output_folder} is either a core repository folder or "
                "a subfolder in a core repository folder."
            )
            try:
                continue_input = input("Continue (folder will be overwritten)? [y/N] ")
            except (KeyboardInterrupt, EOFError):
                raise Abort("User aborted.")
            if continue_input.lower() not in ["y", "yes"]:
                raise Abort("User aborted.")
        else:
            print(f"Output folder {output_folder} already exists - will overwrite it.")
        _remove_folder(output_folder)

    # (Re)create output folder
    output_folder.mkdir(parents=True)

    # Copy static folders
    for folder in STATIC_DOCS_FOLDERS:
        (output_folder / folder).mkdir()
        for child in (REPO_ROOT / "docs" / folder).iterdir():
            shutil.copyfile(child, output_folder / folder / child.name)

    # Run md_to_html.py
    rendering_workflow(output_folder)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python build.py <output_path>")
        sys.exit(1)

    try:
        build(Path(sys.argv[1]).resolve().relative_to(REPO_ROOT).resolve())
    except KeyboardInterrupt:
        sys.exit("Keyboard interrupt. Exiting...")
    except Abort as exc:
        print(f"Aborting: {exc}")
        sys.exit()
    except Exception as exc:
        sys.exit(f"Error: {exc}")
