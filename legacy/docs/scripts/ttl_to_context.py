import rdflib
from rdflib.namespace import RDF, OWL, SKOS
import json
import os
from urllib.parse import urljoin
from urllib.request import pathname2url
import warnings


def generate_jsonld_context(ttl_file, predicate_uri, label_uri='http://www.w3.org/2000/01/rdf-schema#label'):
    """
    Generate a JSON-LD context file from a Turtle file.

    Args:
    - ttl_file: Path to the Turtle (.ttl) file.
    - predicate_uri: The URI of the predicate to map to JSON-LD.
    - label_uri: The URI for the label (default is rdfs:label).

    Returns:
    - A Python dictionary representing the JSON-LD context.
    """
    g = rdflib.Graph()
    g.parse(ttl_file, format='ttl')
    
    CHAMEO = rdflib.Namespace("https://w3id.org/emmo/domain/chameo#")
    g.bind('chameo', CHAMEO)

    EMMO = rdflib.Namespace("https://w3id.org/emmo#")
    g.bind('emmo', EMMO)

    context = {}
    object_properties  = {}
    other_entries = {}
    namespace_prefixes= {}
    predicate = rdflib.URIRef(predicate_uri)
    label = rdflib.URIRef(label_uri)
    existing_keys = set()

    for s, p, o in g:
        if (s, RDF.type, OWL.ObjectProperty) in g:
            # If the subject is an OWL.ObjectProperty
            label_value = g.value(s, SKOS.prefLabel)
            if label_value:
                object_properties[str(label_value)] = {
                    "@id": str(s),
                    "@type": "@id"
                }
                
                
        elif p == predicate:
            # Normal context entry
            # Use the label as key if it exists
            #label_value = g.value(s, label) if g.value(s, label) else str(s)
            label_value = str(s)
            other_entries[str(o)] = str(label_value)
            

    # Add namespace prefixes to the context
    for prefix, uri in g.namespace_manager.namespaces():
        if len(prefix) >= 2:
            namespace_prefixes[prefix] = str(uri)

    # Sort the entries alphabetically
    sorted_object_properties = dict(sorted(object_properties.items()))
    sorted_other_entries = dict(sorted(other_entries.items()))
    sorted_namespace_prefixes = dict(sorted(namespace_prefixes.items()))

    # Merge the sorted entries
    context = {
        "@context": {
            **sorted_namespace_prefixes,
            **sorted_object_properties,
            **sorted_other_entries
        }
    }
    
    print("Namespaces:")
    for prefix, uri in g.namespace_manager.namespaces():
        print(f"{prefix}: {uri}")

    
    return context


# Example usage
filename = 'battinfo-inferred.ttl'
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
file_path = os.path.join(parent_dir, '..', filename)

# Convert the file path to a file URI
file_uri = urljoin('file:', pathname2url(file_path))

predicate_uri = 'http://www.w3.org/2004/02/skos/core#prefLabel'
context = generate_jsonld_context(file_uri, predicate_uri)

# Determine the path for saving the context file in the same directory as the HTML docs
context_file_path = os.path.join(os.path.dirname(parent_dir), 'context/context.json')

# Save to JSON file
with open(context_file_path, 'w') as f:
    json.dump(context, f, indent=4)
