



########## RENDER HTML TEMPLATE ################
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

def render_html_bottom() -> str:
    return """
            </body>
        </html>
        """
    
