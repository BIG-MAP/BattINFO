import markdown
from html_styling import render_html_top, render_html_bottom



def load_md_into_html(path:str)-> str:
    
    with open(path, 'r', encoding="utf-8") as file:
        markdown_text = file.read()

    # Convert Markdown to HTML
    html = markdown.markdown(markdown_text)
    return html



########### RUN THE RENDERING WORKFLOW ##############

def rendering_workflow():

     ########## PAGES 
    pages = [
        {"filename":"about.html", 
         "path":"./docs_dev/assets/about.md"},

        {"filename":"index.html", 
         "path":"./docs_dev/assets/index.md"},

         {"filename":"contribute.html", 
         "path":"./docs_dev/assets/contribute.md"},
    ]

    ########## GENERATE PAGES 

    for page in pages:


        html = render_html_top()
        html += load_md_into_html(page["path"])
        html += render_html_bottom()

        with open("./docs_dev/"+page["filename"], "w", encoding="utf-8") as f:
            f.write(html)



if __name__ == "__main__":

    rendering_workflow()
