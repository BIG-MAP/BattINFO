from rdflib import Graph, Namespace, Literal
from rdflib.namespace import RDF, RDFS, SKOS
import sys

def add_foops_recommendations(input_file, output_file):
    """
    Reads an ontology from a TTL file, adds extra relationships to comply with FOOPS recommendations,
    and writes the updated ontology to a new TTL file.

    Args:
        input_file (str): Path to the input TTL file.
        output_file (str): Path to the output TTL file where updated ontology will be saved.
    """
    # Define the EMMO namespace
    EMMO = Namespace("https://w3id.org/emmo#")

    # Read the original TTL file content with UTF-8 encoding
    with open(input_file, 'r', encoding='utf-8') as file:
        ttl_content = file.read()

    # Load the TTL content into an RDFLib graph
    graph = Graph()
    graph.parse(data=ttl_content, format='turtle')

    # Prepare to collect new triples as a list
    new_triples = []

    # Duplicate skos:prefLabel triples as rdfs:label triples
    for subj, pred, obj in graph.triples((None, SKOS.prefLabel, None)):
        if isinstance(obj, Literal):
            new_triples.append((subj, RDFS.label, obj))
    
    # Duplicate EMMO-specific annotation triples as rdfs:comment triples
    for subj, pred, obj in graph.triples((None, EMMO.EMMO_967080e5_2f42_4eb2_a3a9_c58143e835f9, None)):
        if isinstance(obj, Literal):
            new_triples.append((subj, RDFS.comment, obj))

    # Add new triples to the graph
    for triple in new_triples:
        graph.add(triple)

    # Serialize the graph to the output file with UTF-8 encoding
    graph.serialize(destination=output_file, format='turtle')

def main():
    """
    Main function to handle command-line arguments and invoke the FOOPS compliance update.
    """
    # Check for command-line arguments
    if len(sys.argv) != 3:
        print("Usage: python convert_ttl.py <input_file> <output_file>")
        sys.exit(1)

    # Input and output file paths from command-line arguments
    input_file = sys.argv[1]
    output_file = sys.argv[2]

    # Update the TTL file with FOOPS recommendations
    add_foops_recommendations(input_file, output_file)

    print(f"Updated TTL file saved as {output_file}")

if __name__ == "__main__":
    main()
