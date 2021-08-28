# mameXML2SQLite3
Mame XML data to SQLite database.

## What's this
This is a project to manage your custom set of games of a mame romset.  

As you maybe know, a game romset of mame is composed of several roms, bios, samples. It also some addons as cheats, snaps, artworks.... On a splitted Romset some cloned-games depends on their parent's games. Some games needs a bios. So it's difficult to separate your custom set of games.  

This script allows you to manage in an efficent way your custom set of games from a romset.  

It takes a mame.xml file, generates a SQLite3 database and offers some functions in a simple terminal interface.  

This script runs on a python3 interpreter, I use it on a linux environment, but it should work on windows also.  

Tested on mame 1.49 romset.  

See wiki pages for more information..
