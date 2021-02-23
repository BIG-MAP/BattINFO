#!/bin/sh
# Bash script for generating documentation
set -e
set -x

rootdir=$(git rootdir)
ontodocdir=$rootdir/doc/ontodoc
tmpdir=$ontodocdir/tmp
pagesdir=$tmpdir/gh-pages

# Generate documentation
$ontodocdir/mkdoc.sh

# Check up gh-pages
if ! [ -d $pagesdir ]; then
    git clone --branch=gh-pages --single-branch \
        git@github.com:BIG-MAP/OntoBATT.git $pagesdir
fi

# Copy documentation to gh-pages
# FIXME - generate separate index.html with links to versions
cd $pagesdir
cp -u $tmpdir/battinfo.html index.html

# Update gh-pages
git pull origin gh-pages
git add index.html
git commit -m "Update BattINFO reference documentation"
git push origin gh-pages
