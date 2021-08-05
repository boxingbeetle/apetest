# SPDX-License-Identifier: BSD-3-Clause

# TODO: It would be better to have this as a CSS file.

CSS = """
body {
    margin: 0;
    padding: 0;
    background-color: #FFFFFF;
    color: black;
    font-family: vera, arial, sans-serif;
}
a {
    color: black;
}
h1, h2 {
    border-top: 1px solid #808080;
    border-bottom: 1px solid #808080;
}
h1 {
    margin: 0 0 12pt 0;
    padding: 3pt 12pt;
    background-color: #E0E0E0;
}
h2 {
    padding: 2pt 12pt;
    background-color: #F0F0F0;
}
h3, p, dl {
    padding: 1pt 12pt;
}
h3.pass {
    background-color: #90FF90;
}
h3.fail {
    background-color: #FF9090;
}
li {
    line-height: 125%;
}
li.error {
    list-style-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 10 10" version="1.1"><path fill="%23e00" d="M0,5 a5,5 0 0 0 10,0 5,5 0 0 0 -10,0 Z M5,3.75 6.75,2 8,3.25 6.25,5 8,6.75 6.75,8 5,6.25 3.25,8 2,6.75 3.75,5 2,3.25 3.35,2 Z"/></svg>');
}
li.warning {
    list-style-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 10 10" version="1.1"><path fill="%23f70" d="M1,10 h8 a1,1 0 0 0 0.866,-1.5 l-4,-7 a1,1 0 0 0 -1.732,0 l-4,7 a1,1 0 0 0 0.866,1.5 Z M4.5,3 h1 v4 h-1 Z M5,7.75 a0.75,0.75 0 0 1 0,1.5 0.75,0.75 0 0 1 0,-1.5 Z"/></svg>');
}
li.info {
    list-style-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 10 10" version="1.1"><path fill="%2333f" d="M0,5 a5,5 0 0 0 10,0 5,5 0 0 0 -10,0 Z M5,1.25 a1,1 0 0 1 0,2 1,1 0 0 1 0,-2 Z M3.5,4.25 h2 v3 h1 v1 h-3 v-1 h1 v-2 h-1 Z"/></svg>');
}
span.extract {
    background: #FFFFB0;
}
code {
    background: #F0F0F0;
    color: #000000;
}
"""
