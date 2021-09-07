# mameXML2SQLite3
Mame XML data to SQLite database.

## What's this
This is a script to manage your custom set of games of a mame romset.  

As you maybe know, a game romset of mame is composed of several roms, bios, samples. It also has some addons as cheats, snaps, artworks.... On a splitted Romset some cloned-games depends on their parent's games. Some games needs a bios. So it's difficult to separate your custom set of games.  

This script is intended to manage in an efficent way your custom set of games from a romset.  

## How does this script do?  
Basically, it takes a mame.xml file, generates a SQLite3 database and offers some functions in a simple terminal interface.  

This script runs on a python3 interpreter, I use it on a linux environment, but it should also work on windows.  

Tested on mame 149 and 220 romset.  

See wiki pages for more information.. https://github.com/pablo33/mameXML2SQLite3/wiki  

## Why did I do this script?  
I did this script:  
- To know which games works,  
- which of them are clones, if they  need some CHDs files
- to filter games based on certain type of controllers  
- to filter games based on their category  
- to have a organized custom games collection on an arcade cabinet.  
- and just for fun!  

Feel free to submit a new issue if you find any bugs or a new function request. I don't promise anything, just coding it on my spare time.  

Have Fun!
