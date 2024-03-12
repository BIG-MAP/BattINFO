import markdown


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

########## RENDER HTML BOTTOM ################

def render_html_bottom() -> str:
    return """
            </body>
        </html>
        """


########## LOAD MD INTO HTML  ################

def load_md_into_html(path:str)-> str:

    with open(path, 'r', encoding="utf-8") as file:
        markdown_text = file.read()

    # Convert Markdown to HTML
    html = markdown.markdown(markdown_text)
    return html



########### RUN THE RENDERING WORKFLOW ##############

def rendering_workflow():

     # PAGES 
    pages = [
        {"filename":"about.html", 
         "path":"./docs/assets/about.md"},

        {"filename":"index.html", 
         "path":"./docs/assets/index.md"},

         {"filename":"contribute.html", 
         "path":"./docs/assets/contribute.md"},
    ]

    # GENERATE PAGES 

    for page in pages:


        html = render_html_top()
        html += load_md_into_html(page["path"])
        html += render_html_bottom()

        with open("./docs/"+page["filename"], "w", encoding="utf-8") as f:
            f.write(html)



if __name__ == "__main__":

    rendering_workflow()
