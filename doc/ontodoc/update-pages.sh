#!/bin/sh
# Bash script for generating documentation
set -e
set -x

# Directories
rootdir=$(git rev-parse --show-toplevel)
ontodocdir=$rootdir/doc/ontodoc
tmpdir=$ontodocdir/tmp
pagesdir=$tmpdir/gh-pages

# Generate documentation
$ontodocdir/mkdoc.sh

# Check up gh-pages
if ! [ -d $pagesdir ]; then
    git clone --branch=gh-pages --single-branch \
        git@github.com:BIG-MAP/OntoBATT.git $pagesdir
    cd $pagesdir
    git config pull.rebase false
fi

# Update local copy of gh-pages
cd $pagesdir
git pull origin gh-pages

# Copy documentation to gh-pages
# FIXME - generate separate index.html with links to versions
cp -u $tmpdir/battinfo.html index.html

# Update gh-pages
if git add index.html; then
    git commit -m "Update BattINFO reference documentation"
    git push origin gh-pages
fi
