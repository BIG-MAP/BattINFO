from emmo import get_ontology, World
import os
import types

onto = get_ontology('battinfo.ttl').load()

world = World()
new_electrochemistry = world.get_ontology("http://emmo.info/BattINFO/electrochemistry#")

with new_electrochemistry: 
    for i in onto.get_entities():
        #print(i, i.namespace.ontology.name)
        if i.namespace.ontology.name in ['electrode', 'saltbridge']:
            print(i)
            temp = types.new_class(i.name, (i.__class__,))
            temp.is_a = i.is_a
            for k,v in i.get_annotations().items():
                setattr(temp, k, v)


        #i.namespace.ontology = get_ontology("http://emmo.info/BattINFO/electrochemistry#")

#ec_onto = [i for i in onto.get_imported_ontologies(
#    recursive=True) if i.name == 'electrochemistry'][0]

thisdir = os.path.abspath(os.path.dirname(__file__))
#onto.sync_attributes()
new_electrochemistry.save(os.path.join(thisdir, 'electrochemistry_2.ttl'), overwrite=True)
