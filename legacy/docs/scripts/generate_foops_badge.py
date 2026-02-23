from fetch_foops_score import fetch_foops_score

def generate_badge(score):
    score_percentage = round(score * 100, 2)
    url = f"https://img.shields.io/badge/FOOPS%20Score-{score_percentage}%25-brightgreen"
    return url

def update_readme(badge_url):
    readme_file = "README.md"
    with open(readme_file, "r") as file:
        content = file.readlines()

    with open(readme_file, "w") as file:
        for line in content:
            if line.startswith("![FOOPS Score]"):
                file.write(f"[![FOOPS Score]({badge_url})](https://foops.linkeddata.es/FAIR_validator.html)\n")
            else:
                file.write(line)

if __name__ == "__main__":
    ontology_uri = "https://w3id.org/emmo/domain/battery"
    score = fetch_foops_score(ontology_uri)
    badge_url = generate_badge(score)
    update_readme(badge_url)
    print(f"Updated README with FOOPS score badge: {badge_url}")
