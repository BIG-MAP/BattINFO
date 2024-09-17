import requests
import json

def fetch_foops_score(ontology_uri):
    url = "https://foops.linkeddata.es/assessOntology"
    headers = {
        "accept": "application/json;charset=UTF-8",
        "Content-Type": "application/json;charset=UTF-8"
    }
    data = {
        "ontologyUri": ontology_uri
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        result = response.json()
        score = result['overall_score']
        return round(score, 2)
    else:
        raise Exception(f"Failed to fetch FOOPS score: {response.status_code}")

if __name__ == "__main__":
    ontology_uri = "https://w3id.org/emmo/domain/battery"
    score = fetch_foops_score(ontology_uri)
    print(f"FOOPS score for {ontology_uri}: {score}")
