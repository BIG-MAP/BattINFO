from emmo import get_ontology, World
import os

onto = get_ontology('battinfo.ttl').load()

# world = World()
# new_electrochemistry = get_ontology('new_electrochemistry.ttl')


for i in onto.get_entities():
    if i.namespace.ontology.name in ['electrode', 'saltbridge']:
        i.namespace.ontology = get_ontology("http://emmo.info/BattINFO/electrochemistry#")

ec_onto = [i for i in onto.get_imported_ontologies(
    recursive=True) if i.name == 'electrochemistry'][0]

thisdir = os.path.abspath(os.path.dirname(__file__))
onto.save(os.path.join(thisdir, 'electrochemistry.ttl'), overwrite=True)
