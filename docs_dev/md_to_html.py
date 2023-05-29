import os
import markdown
from bs4 import BeautifulSoup

script_directory = os.path.dirname(os.path.abspath(__file__))

########## BANNER ##############
jpeg_path = os.path.abspath(script_directory + '\banner.jpg')
BANNER_HTML =  '''
<div class="banner">
    <a href="index.html">
        <img src="banner.jpg" alt="Banner Image">
    </a>
</div>
'''.format(jpeg_path)


######## CSS FORMATTING #########
CSS_STRING = '''
body {
    font-family: Arial, sans-serif;
    margin: 40px auto;
    max-width: 800px;
    padding: 0 20px;
}

.banner {
    display: flex;
    flex-direction: column;
    align-items: center;
    margin: 0 auto;
    max-width: 100%;
    overflow: hidden;
}


h1, h2, h3 {
    color: #333;
}

h1 {
    font-size: 24px;
    margin-bottom: 20px;
}

h2 {
    font-size: 20px;
    margin-bottom: 15px;
}

h3 {
    font-size: 18px;
    margin-bottom: 10px;
}

p {
    line-height: 1.5;
}

a {
    color: #007bff;
}

code {
    background-color: #f8f8f8;
    padding: 2px 4px;
    font-family: Consolas, Monaco, monospace;
}

blockquote {
    border-left: 3px solid #333;
    margin: 0;
    padding-left: 10px;
    color: #777;
}

hr {
    border: none;
    border-top: 1px solid #ccc;
    margin: 20px 0;
}
'''

def from_md_to_hmtl(body_html:str):
    # Create a BeautifulSoup object for the final HTML structure
    final_soup = BeautifulSoup(features="html.parser")

    # Create the <head> tag and append the <style> tag
    head_tag = final_soup.new_tag('head')
    style_tag = final_soup.new_tag('style')
    style_tag.string = CSS_STRING
    head_tag.append(style_tag)
    final_soup.append(head_tag)

    # Create the <body> tag and append the banner HTML and markdown HTML
    body_tag = final_soup.new_tag('body')
    body_tag.append(BeautifulSoup(BANNER_HTML, 'html.parser'))
    body_tag.append(BeautifulSoup(body_html, 'html.parser'))
    final_soup.append(body_tag)

    return final_soup



if __name__ == "__main__":


    list_md_paths = ["batteries.md", "batteryquantities.md", "contribute.md", "electrochemicalquantities.md",
                     "electrochemistry.md","about.md"]
    
    for path_str in list_md_paths:

        full_md_path = script_directory + "/" + path_str

        assert os.path.exists(full_md_path), f"The file {full_md_path} path does not exists."
        
        with open(full_md_path, 'r', encoding="utf-8") as file:
            markdown_text = file.read()

    # Convert Markdown to HTML
        html_body = markdown.markdown(markdown_text)

        final_soup = from_md_to_hmtl(html_body)

        html_path = script_directory + "/" + os.path.splitext(path_str)[0] + ".html"

        with open(html_path, 'w', encoding="utf-8") as file:
            file.write(str(final_soup))