
from rdflib import Graph




########## FUNCTIONS ################


def load_ttl_from_url(url:str)->Graph:
    g = Graph()
    g.parse(url, format="turtle")
    return g



def extract_terms_info_sparql(g: Graph)-> list:

    text_entities = []

    # SPARQL QUERY #
    PREFIXES = """
        PREFIX emmo: <http://emmo.info/emmo#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        """

    list_entity_types = ["IRI", "prefLabel", "Elucidation", "Alternative Label(s)", "IEC Reference", "IUPAC Reference", "Wikipedia Reference"]

    query =  PREFIXES  + """
        SELECT DISTINCT ?iri ?prefLabel ?elucidation ?altlabel ?iecref ?iupacref ?wikipediaref
        WHERE {
            ?iri skos:prefLabel ?prefLabel.

            OPTIONAL { ?iri emmo:EMMO_967080e5_2f42_4eb2_a3a9_c58143e835f9 ?elucidation . }
            OPTIONAL { ?iri skos:altLabel ?altLabel . }
            OPTIONAL { ?iri emmo:EMMO_50c298c2_55a2_4068_b3ac_4e948c33181f ?iecref . }
            OPTIONAL { ?iri emmo:EMMO_fe015383_afb3_44a6_ae86_043628697aa2 ?iupacref . }
        }
        """
        
    qres = g.query(query)

    for hit in qres:    
        hit_dict = {entity_type:str(entity) for entity_type, entity in zip(list_entity_types, hit)}
        text_entities.append(hit_dict)

    text_entities.sort(key=lambda e: e["prefLabel"])

    return text_entities





def generate_markdown(entities_list:list, page_title:str="", page_intro:str=""):
    
    entites_md_text = "# " + page_title
    entites_md_text += page_intro + " \n\n"

    for entity_dict in entities_list:

        entites_md_text += f"*** \n\n"

        pref_label = entity_dict["prefLabel"]
        entites_md_text += f"### {pref_label} \n\n"

        iri = entity_dict["IRI"]
        entites_md_text += f" [{iri}]({iri}) \n\n"

        elucidation = entity_dict["Elucidation"]
        if elucidation != "None":
            entites_md_text += f"{elucidation} \n\n"

        for annotation_key, annotation_value in entity_dict.items():
            if annotation_key not in ["IRI", "prefLabel", "Elucidation"]:
                if annotation_value != "None":
                    entites_md_text += f" *{annotation_key}*: {annotation_value} \n\n"

    return entites_md_text



if __name__ == "__main__":


    ########## PAGES ################
    pages = [
        {"filename":"electrochemicalquantities.md", 
         "page title":"Quantities used in Electrochemistry",
         "page intro": "",
         "url ttl":"https://raw.githubusercontent.com/emmo-repo/domain-electrochemistry/master/electrochemicalquantities.ttl"},

         {"filename":"electrochemistry.md", 
         "page title":"Electrochemistry Concepts",
         "page intro": "",
         "url ttl":"https://raw.githubusercontent.com/emmo-repo/domain-electrochemistry/master/electrochemistry.ttl"},

         {"filename":"batteries.md", 
         "page title":"Battery Concepts",
         "page intro": "",
         "url ttl":"https://raw.githubusercontent.com/emmo-repo/domain-battery/master/battery.ttl"},

         {"filename":"batteryquantities.md", 
         "page title":"Battery Quantities",
         "page intro": "",
         "url ttl":"https://raw.githubusercontent.com/emmo-repo/domain-battery/master/batteryquantities.ttl"},
    ]


    ########## GENERATE PAGES ################

    for page in pages:

        g = load_ttl_from_url(page["url ttl"])

        entities_list = extract_terms_info_sparql(g)

        md_text = generate_markdown(entities_list = entities_list,
                                    page_title = page["page title"],
                                    page_intro = page["page intro"])

        with open("./docs_dev/"+page["filename"], "w", encoding="utf-8") as f:
            f.write(md_text)