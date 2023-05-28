import os
import markdown
from bs4 import BeautifulSoup


############### RESOURCES ##################

# Read the Markdown file
with open('./docs_dev/index.md', 'r') as file:
    markdown_text = file.read()

# Get the path to the SVG file
svg_path_str = './docs_dev/banner.svg'
assert os.path.exists(svg_path_str), f"SVG file '{svg_path_str }' does not exist"
svg_path = os.path.abspath(svg_path_str)

# Get the path to the SVG file
jpeg_path_str = './docs_dev/banner.jpg'
assert os.path.exists(jpeg_path_str), f"SVG file '{jpeg_path_str}' does not exist"
jpeg_path = os.path.abspath(jpeg_path_str)



########### BODY #####################

# Convert Markdown to HTML
html_body = markdown.markdown(markdown_text)



################ BANNER ########################

# Create the top banner HTML
banner_html = '''
<div class="banner">
    <img src="banner.jpg" alt="Banner Image">
</div>
'''.format(jpeg_path)


############# HEAD #####################

# Style the HTML with CSS
css_text = '''
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


########### SOUP OBJECTS #####################

# Create a BeautifulSoup object for the final HTML structure
final_soup = BeautifulSoup(features="html.parser")

# Create the <head> tag and append the <style> tag
head_tag = final_soup.new_tag('head')
style_tag = final_soup.new_tag('style')
style_tag.string = css_text
head_tag.append(style_tag)
final_soup.append(head_tag)

# Create the <body> tag and append the banner HTML and markdown HTML
body_tag = final_soup.new_tag('body')
body_tag.append(BeautifulSoup(banner_html, 'html.parser'))
body_tag.append(BeautifulSoup(html_body, 'html.parser'))
final_soup.append(body_tag)

############# SAVE #################

# Save the styled HTML to a file
with open('./docs_dev/output.html', 'w') as file:
    file.write(str(final_soup))