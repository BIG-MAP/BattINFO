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
        PREFIX emmo: <http://emmo.info/emmo#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        """

    list_entity_types = ["IRI", "prefLabel", "Elucidation", "Alternative Label(s)", "IEC Reference", "IUPAC Reference", "Wikipedia Reference"]

    query =  PREFIXES  + """
        SELECT ?iri ?prefLabel ?elucidation (GROUP_CONCAT(?altLabel; SEPARATOR=", ") AS ?altLabels) ?iecref ?iupacref ?wikipediaref
        WHERE {
            ?iri skos:prefLabel ?prefLabel.

            OPTIONAL { ?iri emmo:EMMO_967080e5_2f42_4eb2_a3a9_c58143e835f9 ?elucidation . }
            OPTIONAL { ?iri skos:altLabel ?altLabel . }
            OPTIONAL { ?iri emmo:EMMO_50c298c2_55a2_4068_b3ac_4e948c33181f ?iecref . }
            OPTIONAL { ?iri emmo:EMMO_fe015383_afb3_44a6_ae86_043628697aa2 ?iupacref . }
            OPTIONAL { ?iri emmo:EMMO_c84c6752_6d64_48cc_9500_e54a3c34898d ?wikipediaref . }
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

def render_html_top() -> str:

    top_html = """
        <!DOCTYPE html>
        <html>
            <head>
                <meta charset="UTF-8">
                <title>BattINFO</title>
                <link rel="stylesheet" type="text/css" href="./css/style.css">
                <link rel="icon" type="image/x-icon" href="./assets/favicon.ico">
        </head>  
        <body>      
        """

    banner =  '''
        <div class="banner">
            <a href="index.html">
                <img src="./assets/banner.jpg" alt="Banner Image">
            </a>
        </div>
        '''
    
    return top_html + banner




########## RENDER ENTITIES ################

def entities_to_html(entities: list[dict]) -> str:
    
    html = ""

    for item in entities:

        iri_prefix, iri_suffix = item['IRI'].split("#")

        html += f"""<h3 id="{iri_suffix}">{item['prefLabel']}</h3>"""
        #html += f"""<p class="entity"><a href=#'{item['IRI']}'>{item['IRI']}</a></p>"""
        html += f"""<p class="entity"><i>{item['IRI']}</i></p>"""

        for key, value in item.items():

            if (key not in ['IRI', 'prefLabel']) & (value != "None") & (value != ""):

                if value.startswith("http"):
                    html += f"""<p class="entity"><i>{key}</i>: <a href='{value}'>{value}</a></p>"""
                else:
                    html += f"""<p class="entity"><i>{key}</i>: {value}</p>"""

        html += "<hr>\n"

    return html




########## RENDER HTML BOTTOM ################

def render_html_bottom() -> str:
    return """
            </body>
        </html>
        """



########### RUN THE RENDERING WORKFLOW ##############

def rendering_workflow():

    # PAGES 
    
    pages = [
        {"filename":"electrochemicalquantities.html", 
         "page title":"Quantities used in Electrochemistry",
         "page intro": "",
         "path":"https://raw.githubusercontent.com/emmo-repo/domain-electrochemistry/master/electrochemicalquantities.ttl"},

         {"filename":"electrochemistry.html", 
         "page title":"Electrochemistry Concepts",
         "page intro": "",
         "path":"https://raw.githubusercontent.com/emmo-repo/domain-electrochemistry/master/electrochemistry.ttl"},

         {"filename":"batteries.html", 
         "page title":"Battery Concepts",
         "page intro": "",
         "path":"https://raw.githubusercontent.com/emmo-repo/domain-battery/master/battery.ttl"},

         {"filename":"batteryquantities.html", 
         "page title":"Battery Quantities",
         "page intro": "",
         "path":"https://raw.githubusercontent.com/emmo-repo/domain-battery/master/batteryquantities.ttl"},
    ]



    # GENERATE PAGES 

    for page in pages:

        g = load_ttl_from_url(page["path"])

        entities_list = extract_terms_info_sparql(g)


        html = render_html_top()
        page_title = page["page title"]
        html += f"<h1>{page_title}</h1>\n"
        html += entities_to_html(entities_list)
        html += render_html_bottom()

        with open("./docs_dev/"+page["filename"], "w", encoding="utf-8") as f:
            f.write(html)



if __name__ == "__main__":

    rendering_workflow()