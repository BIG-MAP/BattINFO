from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.abspath(".."))

project = "BattINFO"
copyright = "2021-2025, Simon Clark"
author = "Simon Clark"

extensions = [
    "myst_parser",
    "nbsphinx",
    "sphinx_design",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.intersphinx",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "tasklist",
    "fieldlist",
]

autosectionlabel_prefix_document = True

templates_path = ["_templates"]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

master_doc = "index"

exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "index.md",
    "cell-descriptor-integration.md",
    "cell-descriptor-stable-subset.md",
    "cell-descriptor-standard.md",
    "converter-compatibility.md",
    "dataset-registry-intake-spec.md",
    "editorial-cell-type-workflow.md",
    "resolver.md",
    "validation-roadmap.md",
    "alpha-scope.md",
]

pygments_style = "sphinx"
highlight_language = "python3"

html_theme = "pydata_sphinx_theme"

html_theme_options = {
    "logo": {
        "text": "BattINFO",
        "alt_text": "BattINFO",
    },
    "github_url": "https://github.com/BIG-MAP/BattINFO",
    "navbar_align": "left",
    "navbar_end": ["navbar-icon-links"],
    "secondary_sidebar_items": ["page-toc"],
    "footer_start": ["copyright"],
    "footer_end": [],
    "show_version_warning_banner": False,
}

html_static_path = ["_static"]
html_css_files = ["css/custom.css"]
html_show_sourcelink = False

# nbsphinx — do not re-execute notebooks at build time
nbsphinx_execute = "never"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
}
