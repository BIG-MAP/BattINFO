"""Build documentation from Markdown files."""
from pathlib import Path, PurePosixPath
import sys
from typing import TYPE_CHECKING

import markdown

if TYPE_CHECKING:
    from typing import Union


NON_DOCS_FOLDERS = ["assets", "css", "scripts"]


def render_html_top() -> str:
    """Render the top of the HTML page."""
    top_html = """<!DOCTYPE html>
<html>
    <head>
        <meta charset="UTF-8">
        <title>BattINFO</title>
        <link rel="stylesheet" type="text/css" href="./css/style.css">
        <link rel="icon" type="image/x-icon" href="./assets/favicon.ico">
    </head>
<body>
"""

    banner = """
<div class="banner">
    <a href="index.html">
        <img src="./assets/banner.jpg" alt="Banner Image">
    </a>
</div>
"""

    return top_html + banner


def render_html_bottom() -> str:
    """Render the bottom of the HTML page."""
    return """
    </body>
</html>
"""


def load_md_into_html(path: "Union[str, Path]") -> str:
    """Load Markdown file and convert to HTML."""
    # Read Markdown file
    markdown_text = path.read_text(encoding="utf-8")

    # Convert (and return) Markdown to HTML
    return markdown.markdown(markdown_text)


def rendering_workflow(
    output_path: Path = Path("site"),
) -> None:
    """Workflow for rendering the HTML pages."""
    repo_dir = Path(__file__).resolve().parent.parent.parent.resolve()
    docs_dir = repo_dir / "docs"

    if not output_path.is_absolute():
        # Relative path - Must be relative to the repository root
        output_path = (repo_dir / output_path).resolve()

    # Get all Markdown files NOT in the assets, css, or scripts directories
    md_files = [
        md_file for md_file in (docs_dir).rglob("**/*.md")
        if md_file.relative_to(docs_dir).parts[0] not in NON_DOCS_FOLDERS
    ]

    pages: "dict[str, Union[str, Path]]" = [
        {
            # Filename of HTML file (once rendered)
            "filename": md_file.with_suffix(".html").name,

            # Absolute path to Markdown file
            "source_path": md_file,

            # Relative path from/within docs folder
            "output_dir": md_file.parent.relative_to(docs_dir),
        }
        for md_file in md_files
    ]

    # GENERATE PAGES
    for page in pages:
        html = render_html_top()
        html += load_md_into_html(page["source_path"])
        html += render_html_bottom()

        # Write HTML to file
        # The new file's folder is created if it doesn't already exist.
        html_file_folder = output_path / page["output_dir"]
        html_file_folder.mkdir(parents=True, exist_ok=True)

        # The new file will be created relative to the output path similar to the
        # source file's location relative to the docs folder.
        (html_file_folder / page["filename"]).write_text(html, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        output_path = sys.argv[1]
    else:
        output_path = "site"

    output_path = Path(PurePosixPath(output_path))

    try:
        rendering_workflow(output_path)
    except KeyboardInterrupt:
        sys.exit("Keyboard interrupt. Exiting...")
    except Exception as exc:
        sys.exit(f"Error: {exc}")
