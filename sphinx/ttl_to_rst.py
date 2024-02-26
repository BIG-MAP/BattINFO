from rdflib import Graph



########## LOAD TTL ################


def load_ttl_from_url(url:str)->Graph:
    g = Graph()
    g.parse(url, format="turtle")
    return g




########## QUERY TLL ################

def extract_terms_info_sparql(g: Graph)-> list:

    text_entities = []

    # SPARQL QUERY #
    PREFIXES = """
        PREFIX emmo: <https://w3id.org/emmo#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        """

    list_entity_types = ["IRI", "prefLabel", "Elucidation", "Alternative Label(s)", "IEC Reference", "IUPAC Reference", "Wikipedia Reference", "Wikidata Reference", "Comment", ]

    query =  PREFIXES  + """
        SELECT ?iri ?prefLabel ?elucidation (GROUP_CONCAT(?altLabel; SEPARATOR=", ") AS ?altLabels) ?iecref ?iupacref ?wikipediaref ?wikidataref ?comment
        WHERE {
            ?iri skos:prefLabel ?prefLabel.

            OPTIONAL { ?iri emmo:EMMO_967080e5_2f42_4eb2_a3a9_c58143e835f9 ?elucidation . }
            OPTIONAL { ?iri skos:altLabel ?altLabel . }
            OPTIONAL { ?iri emmo:EMMO_50c298c2_55a2_4068_b3ac_4e948c33181f ?iecref . }
            OPTIONAL { ?iri emmo:EMMO_fe015383_afb3_44a6_ae86_043628697aa2 ?iupacref . }
            OPTIONAL { ?iri emmo:EMMO_c84c6752_6d64_48cc_9500_e54a3c34898d ?wikipediaref . }
            OPTIONAL { ?iri emmo:EMMO_26bf1bef_d192_4da6_b0eb_d2209698fb54 ?wikidataref . }
            OPTIONAL { ?iri rdfs:comment ?comment . }
        }

        GROUP BY ?iri ?prefLabel ?elucidation

        """
        
    qres = g.query(query)

    for hit in qres:    
        hit_dict = {entity_type:str(entity) for entity_type, entity in zip(list_entity_types, hit)}
        text_entities.append(hit_dict)

    text_entities.sort(key=lambda e: e["prefLabel"])

    return text_entities





########## RENDER HTML TOP ################

def render_rst_top() -> str:

    top_rst = """
===========
Class Index
===========

"""

    return top_rst




########## RENDER ENTITIES ################

def entities_to_rst(entities: list[dict]) -> str:
    
    rst = ""

    for item in entities:

        try:
            iri_prefix, iri_suffix = item['IRI'].split("#")
        except ValueError:
            print("Error splitting string:", item['IRI'])
            # Handle the error or continue with the next item
            continue

        rst += ".. raw:: html\n\n"
        rst += "   <div id=\"" + iri_suffix + "\"></div>\n\n"
        
        rst += item['prefLabel'] + "\n"
        for ind in range(len(item['prefLabel'])):
            rst += "-"
        rst += "\n\n"

        rst += "* " + item['IRI'] + "\n\n"
        
        rst += ".. raw:: html\n\n"
        indent = "  "
        rst += indent + "<table class=\"element-table\">\n"
        for key, value in item.items():

            if (key not in ['IRI', 'prefLabel']) & (value != "None") & (value != ""):

                rst += indent + "<tr>\n"
                rst += indent + "<td class=\"element-table-key\"><span class=\"element-table-key\">" + key + "</span></td>\n"
                if value.startswith("http"):
                    value = f"""<a href='{value}'>{value}</a>"""
                value = value.encode('ascii', 'xmlcharrefreplace')
                value = value.decode('utf-8')
                value = value.replace('\n', '\n' + indent)
                rst += indent + "<td class=\"element-table-value\">" + value + "</td>\n"
                rst += indent + "</tr>\n"

        rst += indent + "</table>\n"
        rst += "\n\n"

    return rst


########## RENDER RST BOTTOM ################


def render_rst_bottom() -> str:
    return """
    
        """


########### RUN THE RENDERING WORKFLOW ##############


def rendering_workflow():

    # PAGES
    ttl_modules = [
        {"section title": "BattINFO",
         "path": "./battinfo-inferred.ttl"}
    ]

    # GENERATE PAGES
    rst_filename = "battinfo.rst"

    rst = render_rst_top()

    for module in ttl_modules:

        g = load_ttl_from_url(module["path"])

        entities_list = extract_terms_info_sparql(g)
        
        page_title = module["section title"]
        rst += page_title + "\n"
        for ind in range(len(page_title)):
            rst += "="
        rst += "\n\n"
        rst += entities_to_rst(entities_list)

    rst += render_rst_bottom()

    with open("./sphinx/"+ rst_filename, "w+", encoding="utf-8") as f:
        f.write(rst)



if __name__ == "__main__":

    rendering_workflow()
