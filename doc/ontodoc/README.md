Generate documentation for BattINFO
===================================
This directory contains the needed templates, introductory text and
figures for generating a reference documentation of BattINFO.

The documentation is generated using EMMO-python and pandoc. Just run the
script

    mkdoc.sh


Content of this directory
-------------------------
### `ontodoc` templates with introductory text and document layout
  * [battinfo.md](battinfo.md): Main template. It includes the other
    templates.
  * [introduction.md](introduction.md): Introductory text.
  * [classes.md](classes.md): Introduction and sections for Classes
  * [figs](figs): Figures used in the introduction.

### `pandoc` configuration files
  * [battinfo-meta.yaml](battinfo-meta.yaml): Metadata for BattINFO, like
    title, authers, abstract, etc.
  * [pandoc-args.yaml](pandoc-args.yaml): General pandoc options.
  * [pandoc-html-args.yaml](pandoc-html-args.yaml): Additional pandoc options
    for html generation.
  * [pandoc-pdf-args.yaml](pandoc-pdf-args.yaml): Additional pandoc options
    for pdf generation.
  * [pandoc-html.css](pandoc-html.css): css file used for html generation.
  * [pandoc-template.html](pandoc-template.html): Modified copy of the
    standard pandoc html template with a small adjustment for the author list.
  * [pandoc-template.tex](pandoc-template.tex): Modified copy of the
    standard pandoc latex template with a small adjustment for the author list.
