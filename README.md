# economist-epub-creator
A script to convert your economist online subscription into an epub format. Please note this is intedned to be used only if you have an economist subscription. 

# Requirements 

1. Install requirements.txt
1. Install pandoc https://pandoc.org/installing.html
1. Run create a virtual environment and install the dependencies
1. You can run `EconomistEpubCreator("cookie").create_latest_edition_epub() where the cookie can be taken from your current session in the browser

# Getting from epub to your kindle

You can use [Calibre](https://calibre-ebook.com/) to transfer the epub. I had a difficult time using 
email but I like Calibre

# Notes

This will break when economist updates their API and it doesnt work with interactive articles so please
feel free to push up a PR.