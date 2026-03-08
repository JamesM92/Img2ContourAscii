# Img2ContourAscii
Img to Ascii converter that treats the characters as more than pixels, individual characters are selected not just for brightness but with consideration for contour following.

# Full Credit To Alex Harri
Proper Recognition and credit must be given to Alex Harri for the idea used here. The original concept and idea was well documented in his blog post on his website. https://alexharri.com/blog/ascii-rendering . Although he was not involved in this programs developement it was his blog post that explained the core concepts needed to make this work.

He has a full interactive typescript code on his websites git repository. https://github.com/alexharri/website

# AI Generated
All the code contained was made by chat gpt, I did no coding myself. 

# Details of use.

This script is made to be used as a command line tool to convert an image to asci art. But it is a bit heavier than normal as it uses 6D vector computation. This allows the characters to be selected not just on a per pixel bightness aspect, but also in a locations intensity aspect. 

This means that if you have an angled line crossing the middle of a character, it will try to pic characters than are more closely aligned with the actual edge, more than just the new averaged brightness.

