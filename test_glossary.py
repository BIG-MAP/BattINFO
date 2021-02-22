#!/usr/bin/env python3

from emmo import get_ontology

battinfo = get_ontology('battinfo.ttl').load(url_from_catalog=True)

glossary = {}
with open('glossary.txt') as f:
    for line in f:
        l = line.split('\t')
        try:
            glossary[l[0]] = l[1]
        except:
            pass
missing_classes = []
included_classes = []
for key in glossary.keys():
    if [key] in [e.prefLabel for e in battinfo.get_entities()]:
        included_classes.append(key)
    else:
        missing_classes.append(key)

print('Classes in glossary missing in battinfo:\n', missing_classes)
        
print('-'*40)
classes_missing_in_glossary = []
for e in battinfo.get_entities():
    if str(e).split('.')[0] == 'BattINFO' and str(e).split('.')[1] not in glossary.keys():
        classes_missing_in_glossary.append(e)
print('Classes in battinfo missing in glossary.txt:\n', classes_missing_in_glossary)
