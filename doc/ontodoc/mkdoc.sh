#!/bin/sh
# Bash script for generating documentation
set -e
set -x

rootdir=$(git rootdir)
ontodocdir=$rootdir/doc/ontodoc
tmpdir=$ontodocdir/tmp

cd $ontodocdir

mkdir -p $tmpdir/figs
cp -u $rootdir/bigmap.png $tmpdir/figs/.

ontograph -m $rootdir/battinfo.ttl $tmpdir/battinfo-structure.png
ontoconvert -si $rootdir/battinfo.ttl $tmpdir/battinfo-inferred.ttl

ontodoc --template=battinfo.md --format=html $tmpdir/battinfo-inferred.ttl \
        $tmpdir/battinfo.html


# Some goes wrong when generating pdf
#ontodoc --template=battinfo.md $tmpdir/battinfo-inferred.ttl \
#        $tmpdir/battinfo.pdf
