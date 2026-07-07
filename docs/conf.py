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
    "sphinxcontrib.autodoc_pydantic",
    "sphinx.ext.napoleon",
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.intersphinx",
]

# The Python API page includes python-api.md as a fragment whose headings
# start at H2 by design (the .rst include supplies the H1).
suppress_warnings = ["myst.header"]

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
    # Maintainer-only working notes (see docs/internal/README.md) — kept in-repo
    # but never rendered into the site.
    "internal/**",
    # GitHub-facing docs landing (the rendered site uses index.rst) and the
    # scope note, both linked from README.md but not part of the toctree.
    "index.md",
    "scope.md",
]

pygments_style = "sphinx"
highlight_language = "python3"

html_theme = "pydata_sphinx_theme"

# Versioned docs: the workflow sets DOCS_VERSION ("dev" on main, "vX.Y.Z" on
# tags); the switcher JSON is regenerated at deploy time from the published
# version directories on gh-pages.
import os as _os

_docs_version = _os.environ.get("DOCS_VERSION", "dev")

html_theme_options = {
    "switcher": {
        "json_url": "https://big-map.github.io/BattINFO/switcher.json",
        "version_match": _docs_version,
    },
    "check_switcher": False,  # the URL 404s until the first Pages deploy
    "navbar_end": ["version-switcher", "theme-switcher", "navbar-icon-links"],
    "logo": {
        # Lockups from the canonical brand pack (../brand), copied via html_static_path.
        "image_light": "_static/assets/logo/logo-horizontal.svg",
        "image_dark": "_static/assets/logo/logo-horizontal-on-dark.svg",
        "alt_text": "BattINFO",
    },
    "github_url": "https://github.com/BIG-MAP/BattINFO",
    # Back-links to the website (the "front door"). This reference site owns
    # "how/reference"; battinfo.org owns "why/try". See docs/CONTENT-MODEL.md.
    "external_links": [
        {"name": "Home", "url": "https://battinfo.org"},
        {"name": "Validate", "url": "https://battinfo.org/validate"},
        {"name": "Convert", "url": "https://battinfo.org/convert"},
    ],
    "navbar_align": "left",
    "navbar_end": ["navbar-icon-links"],
    "secondary_sidebar_items": ["page-toc"],
    "footer_start": ["copyright"],
    "footer_end": [],
    "show_version_warning_banner": False,
}

# The brand pack (logo, favicon, tokens) lives at repo-root/brand and is the
# single source of truth. It is copied into the built site's _static/ so the
# docs never fork brand values. See brand/BRAND.md.
html_static_path = ["_static", "../brand"]
html_favicon = "../brand/assets/favicon/favicon.svg"
# tokens.css first so its CSS variables are defined before custom.css maps them.
html_css_files = ["tokens.css", "css/custom.css"]
html_show_sourcelink = False

# nbsphinx — do not re-execute notebooks at build time
nbsphinx_execute = "never"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
}


# autodoc-pydantic — render Field(description=...) as field docs, hide the noise
autodoc_pydantic_model_show_json = False
autodoc_pydantic_model_show_config_summary = False
autodoc_pydantic_model_show_validator_summary = False
autodoc_pydantic_model_show_validator_members = False
autodoc_pydantic_model_show_field_summary = False
autodoc_pydantic_field_show_constraints = False
autodoc_pydantic_model_member_order = "bysource"
autodoc_pydantic_model_undoc_members = False
