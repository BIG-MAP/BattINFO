#!/bin/sh
# Bash script for uploading generated documentation to GitHub Pages
set -ex

# Directories
rootdir=$(git rev-parse --show-toplevel)
ontodocdir=${rootdir}/${ONTODOC_DIR:-doc/ontodoc}
tmpdir=${ontodocdir}/${TMP_DIR:-tmp}

if [ -n "${GITHUB_WORKSPACE}" ]; then
    # Running as a GH Action
    pagesdir=${GITHUB_WORKSPACE}/../${PAGES_DIR}
else
    # Running locally
    pagesdir=${tmpdir}/${PAGES_DIR:-gh-pages}
fi

# Generate documentation
if [ "$1" != "ALREADY_BUILT" ]; then
    ${ontodocdir}/mkdoc.sh
fi

if [ "$1" = "TEST" ]; then
    echo "Not publishing - just testing (for CI)."
    exit
fi

# Copy documentation to gh-pages
# FIXME - generate separate index.html with links to versions
mkdir -p ${pagesdir}
cp -f -u ${tmpdir}/battinfo.html ${pagesdir}/index.html
cp -f -u ${tmpdir}/battinfo.pdf ${pagesdir}/

if [ -n "${GITHUB_WORKSPACE}" ]; then
    # Checkout gh-pages
    cd ${GITHUB_WORKSPACE}
    git checkout -f gh-pages

    # Update gh-pages
    if git add index.html battinfo.pdf ${PUBLISH_ONTOLOGIES_DIR:-ontology}; then
        git commit -m "Update BattINFO documentation & ontologies"
        git push origin gh-pages
    else
        echo "No changes to commit."
    fi
fi
