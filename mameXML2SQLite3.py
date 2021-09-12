#!/usr/bin/python3
# -*- encoding: utf-8 -*-

__version__ = "0.44beta"
__author__  = "pablo33"
__doc__		= """
	This software helps you managing a Mame Romset.
	It also parses mame XML file and setups a SQLite3 Database.
	Copies gamesets from a romset, including bios.
	Copies needed or all bios on a spare bios folder.
	Adds a score field based on progetto besgames.ini file.
	Can create a CSV file with information with roms and actions.
	Process CSV file and do actions like add games to your custom rom folder or remove games.
	Check roms, bios and CHDs integrity.

	Works on a splitted romset.
	generate your mame xml file with the mame version of your romset, 
	or download XML file from the web.
"""

# Standard libray imports
import os, configparser, argparse, sqlite3, re, shutil, zipfile, csv
from sqlite3.dbapi2 import Cursor
from sys import exit
from hashlib import sha1
from glob import glob
from collections import namedtuple

#=====================================
# Custom Error Classes
#=====================================
class NotStringError(ValueError):
	pass
class MalformedPathError(ValueError):
	pass
class EmptyStringError(ValueError):
	pass

#=====================================
# Defaults
#=====================================
romsext		= '.zip'
rsetpath 	= 'romset'
artworkpath	= 'artwork'

crsetpath	= 'customromset'
tmppath		= 'tmp'

#=====================================
# Functions
#=====================================
def itemcheck(pointer):
	''' returns what kind of a pointer is '''
	if type(pointer) is not str:
		raise NotStringError ('Bad input, it must be a string')
	if pointer.find("//") != -1 :
		raise MalformedPathError ('Malformed Path, it has double slashes')
	if os.path.isfile(pointer):
		return 'file'
	if os.path.isdir(pointer):
		return 'folder'
	if os.path.islink(pointer):
		return 'link'
	return ""

class Messages ():
	""" Stores messages, process success and produces outputt prints
		"""
	def __init__ (self, name, verbose = True):
		self.name = name
		self.Wmsg = []	# stores warning messages
		self.Emsg = []	# stores error messages
		self.verbose = verbose
		self.success = True	# It turns False if any error is registered
	
	def add (self, item, text, spool='warning'):
		""" Adds a message, spool can be "warning" or "error"
			messagess are stored as a list of tuples: (item, text)
			item refers to the object that is being affected.
			text is the message.
			"""
		if spool == 'error':
			self.Emsg.append ((item, text))
			self.success = False
		self.Wmsg.append ((item, text))
		if self.verbose:
			print (f'{self.name} : {item} : {text}')
	
	def Emsglist (self, notice = ''):
		""" Output a error messages as a list 
			"""
		if len (self.Emsg)>0:
			returnedlist = []
			a = 10
			print (notice)
			print ('='*a, f' ERRORS for {self.name}','='*a)
			for i in self.Emsg:
				txt = ' : '.join([self.name, i[0], i[1]])
				returnedlist.append(txt)
				print (txt)
			return returnedlist

	def Wmsglist (self, notice = ''):
		""" Output a warning messages as a list 
			"""
		if len (self.Wmsg)>0:
			print (notice)
			returnedlist = []
			a = 10
			print ('='*a, f' Warnings for {self.name}','='*a)
			for i in self.Wmsg:
				txt = ' : '.join([self.name, i[0], i[1]])
				returnedlist.append(txt)
				print (txt)

	def Resumelist (self, notice = ''):
		""" Prints a resume of errors / warnings
			"""
		print (notice)
		if len (self.Emsg) > 0:
			self.Emsglist(notice='Errors encountered')
			print ("Errors encountered")
		elif len (self.Wmsg) > 0:
			self.Wmsglist(notice='Warnings encountered')
			print ("Seems OK, see warnings if you experience problems.")
		else:
			print ("All OK!")
	
	def mix (self, msg):
		""" Mixes another msg spool object into this
			"""
		if msg != None:
			for i in msg.Wmsg:
				self.add(msg.name,f"({' : '.join(list(i))})")
			for i in msg.Emsg:
				self.add(msg.name,f"({' : '.join(list(i))})", spool='error')

def createSQL3 (xmlfile):
	""" This function reads an XML file and creates a correspondent .sqlite3 file
		it returns the new SQLite3 DB path
		"""

	### Checking and initializing the Database
	dbpath = os.path.splitext(xmlfile)[0] + ".sqlite3"
	if itemcheck (dbpath) == 'file':
		con = sqlite3.connect (dbpath) # it creates one if file doesn't exists
		xmlversion = con.execute ("SELECT value FROM xmlheads WHERE key='version'").fetchone()[0]
		print (f"Working with database for Mame XMLversion {xmlversion}")
		return (dbpath)
	elif itemcheck (xmlfile) != 'file':
		print (f'I can not find mame.xml file: {xmlfile}\nPlease create the file with your mame\nmame -listxml > mame.xml')
		exit()
	else:
		print ("Generating a new SQLite database. Be patient.")
		con = sqlite3.connect (dbpath) # it creates one if file doesn't exists
	class Readxmlline:
		""" Reader object based on a line of XML file.
			"""
		def __t2dtags__ (self, txt):
			""" converts attributes string tag to a dictionary
				"""
			if txt == None or len(txt)==0:
				return None
			string = txt
			if string.endswith("/"):
				string = string[:-1]
				self.clos = True
			keys, values = [], []
			for i in re.finditer (' ?([^\"]+)=\"([^\"]*)\"',string):
				keys.append (i.group(1))
				values.append (i.group(2))
			return dict(list(zip(keys,values)))
			
		def __init__(self,l):
			tagg = None
			attr = None
			text = None
			clos = False
			
			# Search for <tag attributes>
			res = re.search (r"<([a-z_]+) (.*)>",l)
			if res != None:
				tagg = res.group(1)
				attr = res.group(2)
				clos = None
			else:
				## Search for <tag>txt</tag>.
				res = re.search (r"<([a-z]+)>(.*)</\1>",l)
				if res != None:
					tagg = res.group(1)
					text = res.group(2)
					clos = True
				else:
					# Search for </tags>
					res = re.search ("</([^\"]*)>",l)
					if res != None:
						tagg = res.group(1)
						clos = True
			self.clos = clos	# Indicates that the tag was closed
			self.tagg = tagg	# Tag <tag atributes>text</tag>
			self.text = text	# text <tag atributes>text</tag>
			self.attr = self.__t2dtags__(attr)   # attributes in a dictionary way

		def data (self):
			""" Returns read line data
				"""
			return (self.tagg, self.attr, self.text)

	def xmlversion (xmlfile):
		""" Searchs for xml version file. Example:
			<mame build="0.220 (unknown)" debug="no" mameconfig="10">
			returns: 220
			"""
		#line reader:
		fh = open(xmlfile)
		for i in fh:
			line = Readxmlline(i)
			if line.data()[0] == "mame":
				buildattr = line.data()[1]["build"]
				return int(buildattr[2:5])
		print ("No version found: exitting")
		exit()

	### Retrieving XMLversion for field assignaments
	xmlversion = xmlversion (xmlfile)
	print (f"Found mame XML {xmlversion} version")
	Table = dict()
	field_table = namedtuple ('table',['Tagg','Txt','Attrib','Tablename','Fieldsdefaults','Fieldstype','Dependant'])
	### Now define Wich tags are retrieved from XML
	# There are 6 tables: 
	# 	one table for game information 		(there is only one value for the game)
	#	one table for file rom information	(there are some values for a game)
	#	one table for device rom information(there are some values for a game)
	# 	one table for CHDs (disks) information (there are some CHDs for a game)
	#	one table for samples rom information(there are some values for a game)
	#	one table for controls information (there are some values for a game)

	# for each table, define which tags, attrib, text contains data to fetch from the XML
	# it will find attributes in this tags: <tag attribute=value/>  ....  or ....  <tag>text</tag>
	# Also informs if a table is dependant of the main game table.

	# There is a gap in the way of XML generated by MAME, so, for now there is 2 possible definitions on table-games

	if xmlversion <=  162:	
		Table ['games'] = field_table (
			Tagg	=("game","display","driver","input"),
			Txt		=("description","year","manufacturer"),
			Attrib	=[
					"name",
					"sourcefile",
					"cloneof",
					"romof",
					"isbios",
					"isdevice",
					"ismechanical",
					"runnable",
					"type",
					"rotate",
					"status",
					"emulation",
					"color",
					"sound",
					"graphic",
					"savestate",
					"players",
					"buttons",
					"coins",
					],
			Tablename		= 'games',
			Fieldsdefaults	={
					"name": None,
					"sourcefile": None,
					"cloneof": None,
					"romof": None,
					"isbios": None,
					"isdevice": None,
					"ismechanical": None,
					"runnable": None,
					"description": None,
					"year": None,
					"manufacturer": None,
					"type": None,
					"rotate": None,
					"status": None,
					"emulation": None,
					"color": None,
					"sound": None,
					"graphic": None,
					"savestate": None,
					"players": None,
					"buttons": None,
					"coins": None,
					},
			Dependant 	= False,
			Fieldstype	= {
					"name": 			("name"			,"char", "NOT NULL PRIMARY KEY"),
					"sourcefile": 		("sourcefile"	,"char", ""),
					"cloneof":  		("cloneof"		,"char", ""),
					"romof":  			("romof"		,"char", ""),
					"isbios": 			("isbios"		,"bool", ""),
					"isdevice":			("isdevice"		,"bool", ""),
					"ismechanical":		("ismechanical"	,"bool", ""),
					"runnable":			("runnable"		,"bool", ""),
					"description":  	("description"	,"char", ""),
					"year":				("year"			,"char" , ""),
					"manufacturer":  	("manufacturer"	,"char", ""),
					"type":  			("display_type"	,"char", ""),
					"rotate":			("display_rotate"	,"char" , ""),
					"status":  			("driver_status"	,"char", ""),
					"emulation":  		("driver_emulation"	,"char", ""),
					"color":  			("driver_color"		,"char", ""),
					"sound":  			("driver_sound"		,"char", ""),
					"graphic":  		("driver_graphic"	,"char", ""),
					"savestate":  		("driver_savestate"	,"char", ""),
					"players":			("input_players"	,"char", ""),
					"buttons":			("input_buttons"	,"chat", ""),
					"coins":			("input_coins"		,"char", ""),
					},
		)
	else:
		Table ['games'] = field_table (
			Tagg	=("machine","display","driver","input"),
			Txt		=("description","year","manufacturer"),
			Attrib	=[
					"name",
					"sourcefile",
					"cloneof",
					"romof",
					"isbios",
					"isdevice",
					"ismechanical",
					"runnable",
					"type",
					"rotate",
					"status",
					"emulation",
					"savestate",
					"players",
					"buttons",
					"coins",
					],
			Tablename		= 'games',
			Fieldsdefaults	={
					"name": None,
					"sourcefile": None,
					"cloneof": None,
					"romof": None,
					"isbios": None,
					"isdevice": None,
					"ismechanical": None,
					"runnable": None,
					"description": None,
					"year": None,
					"manufacturer": None,
					"type": None,
					"rotate": None,
					"status": None,
					"emulation": None,
					"savestate": None,
					"players": None,
					"buttons": None,
					"coins": None,
					},
			Dependant 		= False,
			Fieldstype	= {
					"name": 			("name"			,"char", "NOT NULL PRIMARY KEY"),
					"sourcefile": 		("sourcefile"	,"char", ""),
					"cloneof":  		("cloneof"		,"char", ""),
					"romof":  			("romof"		,"char", ""),
					"isbios": 			("isbios"		,"bool", ""),
					"isdevice":			("isdevice"		,"bool", ""),
					"ismechanical":		("ismechanical"	,"bool", ""),
					"runnable":			("runnable"		,"bool", ""),
					"description":  	("description"	,"char", ""),
					"year":				("year"			,"char" , ""),
					"manufacturer":  	("manufacturer"	,"char", ""),
					"type":  			("display_type"	,"char", ""),
					"rotate":			("display_rotate"	,"char" , ""),
					"status":  			("driver_status"	,"char", ""),
					"emulation":  		("driver_emulation"	,"char", ""),
					"savestate":  		("driver_savestate"	,"char", ""),
					"players":			("input_players"	,"char", ""),
					"buttons":			("input_buttons"	,"chat", ""),
					"coins":			("input_coins"		,"char", ""),
					},
		)
	# for Rom Table, define which tags contains attributes to fetch
	Table ['roms'] = field_table (
		Tagg	=("rom",),
		Txt		=(),
		Attrib	=[
				"name",
				"size",
				"crc",
				"sha1",
				"status" ,
				"optional",
				],
		Tablename		= 'roms',
		Fieldsdefaults	= {
				"name": None,
				"size": None,
				"crc": None,
				"sha1": None,
				"status": None ,
				"optional": None,
				},
		Dependant 		= True,
		Fieldstype	= {
				"name": 			("rom_name"			,"char", "NOT NULL"),
				"size": 			("rom_size"			,"int" , ""),
				"crc":	 			("rom_crc"			,"char", ""),
				"sha1": 			("rom_sha1"			,"char", ""),
				"status":			("rom_status"		,"char", ""),
				"optional":			("rom_optional"		,"char", ""),
				},
	)	
	# for device Table, define which tags contains attributes to fetch
	Table ['devs'] = field_table (
		Tagg	=("device_ref",),
		Txt		=(),
		Attrib	=[
				"name",
				],
		Tablename		= 'devs',
		Fieldsdefaults	= {
				"name": None,
				},
		Dependant 		= True,
		Fieldstype	= {
				"name":	("dev_name", "char", "NOT NULL"),				},
	)
	# for disks Table, define which tags contains attributes to fetch
	Table ['disks'] = field_table (
		Tagg	=("disk",),
		Txt		=(),
		Attrib	=[
				"name",
				"sha1",
				"region",
				"index" ,
				"writable",
				],
		Tablename		= 'disks',
		Fieldsdefaults	= {
				"name": None,
				"sha1": None,
				"region": None,
				"index" : None,
				"writable": None,
				},
		Dependant 		= True,
		Fieldstype		= {
				"name":		("dsk_name", "char", "NOT NULL"),
				"sha1": 	("dsk_sha1", "char", ""),
				"region":	("dsk_region", "char", ""),
				"index":	("dsk_index", "char", ""),
				"writable":	("dsk_writable", "char", ""),
				}
	)
	# for samples Table, define which tags contains attributes to fetch
	Table ['samples'] = field_table (
		Tagg	= ("sample",),
		Txt		= (),
		Attrib	= [
				"name",
				],
		Tablename		= 'samples',
		Fieldsdefaults	= {
				"name": None,
				},
		Dependant 		= True,
		Fieldstype		= {
				"name":	("spl_name", "char", "NOT NULL"),				},
	)		
	# for controls Table, define which tags contains attributes to fetch
	Table ['controls'] = field_table (
		Tagg	= ("control",),
		Txt		= (),
		Attrib	= [
				"type",
				],
		Tablename		= 'controls',
		Fieldsdefaults	= {
				"type": None,
				},
		Dependant 		= True,
		Fieldstype		= {
				"type":	("ctrl_type", "char", "NOT NULL"),				},
	)
	
	def agrupatefield (table,field):
		""" Groups multiple values of a dependant field on a new field on games table.
			table: is a dependant table,
			field: is a field on a dependant table.
			Separator is "/"
			"""
		sep = "/"
		cursor = con.execute ('SELECT name FROM games')
		nfield = "_".join([table,field])
		gamecount = 0
		commitevery = 5000
		con.execute (f"ALTER TABLE games ADD {nfield} char")
		con.commit()
		print (f"Poblating database with {table},{field}")
		for g in cursor:
			gamecount += 1
			depcursor = con.execute (f"SELECT {field} FROM {table} WHERE name=?", (g[0],))
			if depcursor == None:
				continue
			agrupatevalue = sep.join(i[0] for i in depcursor)
			con.execute (f"UPDATE games SET {nfield}=? WHERE name=?",(agrupatevalue,g[0],))
			if gamecount % commitevery == 0:
				con.commit()
		con.commit()

	class Game:
		def __init__ (self,con):
			self.con = con
			self.Gdata = dict()
			self.Gdatalist = dict()
			# Init game and roms data table fields
			for i in Table.keys():
				self.Gdata [i] = Table[i].Fieldsdefaults.copy() 
				self.Gdatalist [i] = []
		
		def __datatypeparser__ (self):
			def tobool (value):
				if value == None:
					return False
				elif type(value) is bool:
					return bool	
				elif type(value) is str:
					yes_no = {"yes":True, "no":False}
					if value.lower() in yes_no.keys():
						return yes_no[value.lower()]
				return None
			# for game data
						
			for T in Table.keys():
				if not Table[T].Dependant:
					for i in Table[T].Fieldstype:
						if Table[T].Fieldstype[i][1] == 'int':
							self.Gdata[T][i] = int(self.Gdata[T][i])
						elif Table[T].Fieldstype[i][1] == 'bool':
							self.Gdata[T][i] = tobool (self.Gdata[T][i])
				else:
					newlist = []
					for j in self.Gdatalist[T]:
						newdict = j[1].copy()
						for i in Table[T].Fieldstype:
							if Table[T].Fieldstype[i][1] == 'int':
								newdict[i] = int(newdict[i])
							elif Table[T].Fieldstype[i][1] == 'bool':
								newdict[i] = tobool(newdict[i])
						newlist.append ((j[0],newdict))
					self.Gdatalist[T] = newlist.copy()

		def adddata (self,data):
			""" adds data for the game, data is a tuple from the XML extractor, (see Readxmlline class)
			(tagg, attr,text )
				"""
			for T in Table.keys():
				# Searching on Tagg and attr from input dict
				if data[0] in Table[T].Tagg and data[1]!=None:
					for i in Table[T].Attrib:
						if i in data[1]:
							self.Gdata[T][i] = data[1].get(i)
				# Searching on Tagg and retrieve TXT
				if data[0] in Table[T].Txt:
					self.Gdata[T][data[0]]=data[2]
				# Making a list for multiple values (table dependants)
				if Table[T].Dependant and self.Gdata[T] != Table[T].Fieldsdefaults.copy():
					self.Gdatalist[T].append ((self.Gdata["games"]['name'], self.Gdata[T].copy() ))
					self.Gdata[T] = Table[T].Fieldsdefaults.copy()
					break
		
		def write2db (self):
			""" Write data to Database
				"""
			self.__datatypeparser__()
			for T in Table.keys():
				if not Table[T].Dependant:
					fields = ",".join([Table[T].Fieldstype[i][0] for i in self.Gdata[T]])
					values = [i for i in self.Gdata[T].values()]
					questions = ",".join("?"*len(self.Gdata[T]))
					self.con.execute(f"INSERT INTO {T} ({fields}) VALUES ({questions})", values)
				else:
					for r in self.Gdatalist[T]:
						fields = ",".join([Table[T].Fieldstype[i][0] for i in r[1]]) + ",name"
						values = [i for i in r[1].values()]
						values.append (r[0]) # append key field with game name to the list
						questions = ",".join("?"*len(r[1])) + ",?"
						self.con.execute(f"INSERT INTO {T} ({fields}) VALUES ({questions})", values)

	# Version table
	con.execute (f'CREATE TABLE xmlheads (key char NOT NULL, value char)')
	con.commit()
	con.execute (f"INSERT INTO xmlheads (key,value) VALUES ('version',{xmlversion})")
	con.commit()
	cursor = con.cursor() # object to manage queries
	# game table
	tablefields = ",".join( [i[0]+" "+i[1]+" "+i[2] for i in Table["games"].Fieldstype.values()])
	cursor.execute (f'CREATE TABLE games ({tablefields})')
	# creating dependant tables
	for t in Table:
		if t == 'games':
			continue
		f = Table[t].Fieldstype.values()
		tablefields = "name, " + ",".join( [i[0]+" "+i[1]+" "+i[2] for i in f]) 
		cursor.execute (f'CREATE TABLE {t} ({tablefields})')
	con.commit()

	fh = open(xmlfile)
	gamecount = 0
	commitevery = 5000
	game = Game(con)
	gameretrieve = True  # Forces the closing of a game when a new game tagg is found
	print ("Scanning XML and poblating database")
	for i in fh:
		line = Readxmlline(i)
		if line.data()[0]!= None:
			game.adddata(line.data())
		if line.clos and line.tagg == Table["games"].Tagg[0]:
			# Closing current game and writting data to Database
			game.write2db() # write game to db
			gamecount += 1
			print (gamecount," : ", game.Gdata["games"]['name'])
			game = Game(con) # Init Game object
			if (gamecount % commitevery) == 0:
				con.commit()
	con.commit()
	agrupatefield ('controls','ctrl_type')
	con.close()
	print (f"Working with database for Mame XMLversion {xmlversion}")
	return (dbpath)

def check (file, path):
	""" checks if file is present,
		Todo: check on diverse file extensions
		Todo: also in conbination of upper and lower case. 
		"""
	myfile = namedtuple ('file', ['file','exists']) 
	fullfilepath = os.path.join(path,file + romsext) 
	if itemcheck (fullfilepath) == 'file':
		return myfile (fullfilepath, True)
	return myfile (fullfilepath, False)

def checkfield (con, field):
	""" Checks if a field is at database.
		Returns True in case of found it.
		"""
	cursor = con.execute ("PRAGMA table_info(games)")
	for i in cursor:
		if i[1] == field:
			return True
	return False

class Bios:
	def __init__(self,con):
		# check if bios folder is present
		self.con = con
		self.msg = Messages ('Bios Set')
		self.biospath = os.path.join(crsetpath,'bios')
		if itemcheck(self.biospath) != "folder":
			print (f"creating bios folder at: {self.biospath}")
			os.makedirs (self.biospath)
	def copyallbios (self):
		""" Copy all bios to the bios folder
			"""
		cursor = self.con.execute ("SELECT name,description FROM games WHERE isbios = 1")
		for b in cursor:
			self.copybios (b[0])
		self.msg.Resumelist(notice='Resume')

	def copybios (self,biosname):
		""" copy a bios from romset to bios folder
			"""
		origin 	= check (biosname, romsetpath)
		dest 	= check (biosname, self.biospath)
		if origin.exists == False:
			self.msg.add (biosname,"bios is not present at romset",spool='error')
			return
		if dest.exists == True:
			self.msg.add (biosname,"bios already exist on bios folder",spool='error')
			return
		shutil.copyfile (origin.file, dest.file)
	
	def movebios (self):
		""" Moves all bios files from your custom Rom folder to a bios folder
			"""
		cursor = self.con.execute ("SELECT name FROM games WHERE isbios = 1")
		for biosname in cursor:
			origin	= check (biosname[0], romspath)
			dest	= check (biosname[0], self.biospath)
			if origin.exists == False:
				continue
			if dest.exists == True:
				self.msg.add (biosname[0],"bios already exist on bios folder")
				os.remove (origin.file)
				continue
			shutil.move (origin.file, dest.file)

class Rom:
	""" Represents a game in the Romset. It must be in a .zip file
		Methods: 
			copyrom() 	copy this game from romsetfolder to roms folder, 
						also dependant roms if it is a clone and needed bios.
			removerom()	removes a rom from your custom roms folder. bios, or parent games
						remains there.
			checkrom()	Checks all files for the rom to work.

			it also has this properties:
			self.name		# The name of the game at database
			self.cloneof	# If it is a clone, name of the parent game
			self.romof		# If needs bios or a subsystem, its name
			self.isbios		# True or false
			self.origin		# Tuple: (Place where the rom is at the romset, True or False if file exists)
			self.dest 		# Tuple: (Place where the rom is at the custom romset, True or False if file exists)
			self.devices	# List of the devices needed to run this game
			self.maingame	# Name of the parent game
			self.bios		# Name of the needed bios 
			self.chdgamedir # Directory where the CHDs is at the custom romset
			self.hasroms	# True or False if this rom-game has related roms (some games do not has roms)
		"""
	def __init__(self,con,romname):
		self.con = con
		self.msg = Messages (romname)
		if itemcheck(romspath) != "folder":
			print (f"creating roms folder at: {romspath}")
			os.makedirs (romspath)
		romheads = self.con.execute (f'SELECT name,cloneof,romof, isbios FROM games WHERE name = "{romname}"').fetchone()
		self.stuff = {
			'snap'		: (snappath,	os.path.join(crsetpath,'snap'),		'.*'),
			'cheat'		: (cheatpath,	os.path.join(crsetpath,'cheat'),	'.xml'),
			'samples'	: (samplespath,	os.path.join(crsetpath,'samples'),	'.zip'),
			}
		if romheads == None:
			#print (f'Thereis no rom-game called {romname}')
			self.msg.add('XML',f'Thereis no rom-game called {romname}', spool = 'error')
			self.name 	= None
			self.origin = (None, None)
			self.dest 	= (None, None)
			self.devices = None
			self.maingame, self.bios = None, None
			self.chdgamedir = None
			self.hasroms = None
		else:
			self.name, self.cloneof, self.romof, self.isbios = romheads
			self.origin	= check (romname, romsetpath)
			self.dest 	= check (romname, romspath)
			self.devices = self.__deviceslist__()
			self.maingame, self.bios = self.__maingame__ ()
			self.chdgamedir = os.path.join (romspath, self.maingame)
			self.hasroms = self.__hasroms__()  # True or False if this rom-game has related roms

	def __hasroms__(self):
		""" Indicates if this game-rom has relted roms.
			It is intended to distinguish devices wich has no roms
			"""
		myset = self.__fileromset__ (self.name, "roms", "rom_name")
		if len (myset) == 0:
			return False
		return True

	def removerom (self):
		""" removes a rom file from the custom rom folder
			"""
		self.msg = Messages(self.name)
		if self.name == None:
			return
		if self.dest.exists:
			os.remove (self.dest.file)
			print (f'{self.name} : deleted')
		else:
			self.msg.add (f'{self.name}:Rom ZIP',"File is not at your custom Rom folder")
		self.__removestuff__()
		# removing CHDs
		if itemcheck (self.chdgamedir) == 'folder':
			shutil.rmtree (self.chdgamedir)
		return self.msg

	def copyrom (self):
		""" copy a romgame-pack from the romset folder to the roms folder
			a romga mepack is formed with rom/clone roms, and bios.
			It also:
			- adds devices to the zip-file that are stored as part of the romset
			- TODO: rename existent roms according to its SHA1.
			- adds required CHDs
			- stuff
			"""
		self.msg = Messages(self.name)
		if self.name != None:
			self.__copyfile__()
			self.__fixrnames__()
			if self.romof != None:
				msgs = Rom (con, self.romof).copyrom()
				self.msg.mix(msgs) 
			if self.msg.success:
				self.__adddevs__()
			if self.msg.success:
				self.__addchds__()
				self.__addstuff__()
		return self.msg

	def __fixrnames__(self):
		""" Fixes rom names inside the zip file.
		Takes a list of zipped files, checks their SHA1 and fix their names according to
		the romset database.
		This action operates over the file at custom romset. 
			"""
		print ("checking and fixing rom names:")
		a = zipfile.ZipFile(self.dest.file, mode='r')
		rtmppath = os.path.join(tmppath,self.name)
		a.extractall(rtmppath)
		a.close()
		romlistzip = self.__filezipromset__(self.dest.file)
		rezip = False
		for r in romlistzip:
			filerom = os.path.join(rtmppath,r)
			rfsha = self.__sha1__(filerom)
			cursor = self.con.execute("SELECT rom_name FROM roms WHERE rom_sha1 = ?", (rfsha,)).fetchone()
			if cursor == None:
				self.msg.add(r,"No SHA1 found for this file at the DB")
				continue
			rdbname = cursor[0]
			if rdbname == r and rdbname not in romlistzip:
				continue
			shutil.move (filerom, os.path.join(rtmppath,rdbname))
			self.msg.add(rdbname,"This rom was renamed at the zipfile")
			rezip = True
		if rezip:
			# Create new zip file
			os.remove(self.dest.file)
			a = zipfile.ZipFile(self.dest.file, mode='w')
			filelist = glob (os.path.join(rtmppath,"*.*"))
			for f in filelist:
				a.write(filename = f, arcname = os.path.basename(f))
			a.close()
		if itemcheck(rtmppath)=='folder':
			shutil.rmtree(rtmppath)

	def __copyfile__ (self):
		""" copy a romfile to roms folder
			"""
		if self.origin.exists == False:
			self.msg.add('Rom at romset',f"{self.name} file is not present",spool='error')
			return
		if self.dest.exists == True:
			self.msg.add('Rom at romset',f"{self.name} file already exist")
			return
		shutil.copyfile (self.origin.file, self.dest.file)
		return

	def __adddevs__ (self):
		"""Adds required devs files to the zipped rom at your cursom rom folder
			"""
		gamedevset 	= self.__fileromset__ (self.name,'devs', 'dev_name')
		for device in gamedevset:
			return self.__mergerom__(device)
		return True
	
	def __CHDsfiles__ (self):
		""" returns a list of CHDs files of the romset
			"""
		gamechdset 	= self.__fileromset__ (self.name, 'disks', 'dsk_name')
		filelist = []
		for chd in gamechdset:
			file = os.path.join (chdspath, self.maingame, chd) + '.chd'
			filelist.append (file)
		return filelist

	def __addchds__ (self):
		""" Adds CHDs files to your custom roms
			"""
		for origin in self.__CHDsfiles__():
			file = os.path.basename (origin)
			dest = os.path.join (self.chdgamedir, file)
			if itemcheck (origin) != 'file':
				self.msg.add('CHD',f'CHD not found: {origin}', spool='error')
				return False
			if itemcheck (self.chdgamedir) != 'folder':
				os.mkdir (self.chdgamedir)
			elif itemcheck (dest) == 'file':
				self.msg.add('CHD',f'file already at CHDs folder {dest}')
			shutil.copy (origin, dest)
		return True

	def __maingame__ (self):
		""" Returns the parent name for the game and its bios if any.
			"""
		rname = self.name
		while True:
			cloneof, romof = self.con.execute (f"SELECT cloneof, romof FROM games WHERE name = '{rname}' ").fetchone()
			if cloneof == None:
				return rname, romof 
			rname = cloneof

	def __mergerom__ (self, source):
		""" Merge 2 roms. gets zip files from origin rom and put them into dest rom file.
			dest is a rom placed at your custom roms folder
			origin is a rom placed at your romset folder 
			"""
		zipfileset	= self.__filezipromset__ (self.dest[0])
		if zipfileset == False:
			# Zip file doesn't exist
			return False
		devromset 	= self.__fileromset__ (source,'roms','rom_name')
		if len(devromset) == 0:
			return True
		if devromset in zipfileset:
			self.msg.add (f'roms in {self.dest[0]}',"files are already in the zip file")
			return
		tomerge = devromset.difference(zipfileset)
		sourcepath = check (source, romsetpath)
		if not sourcepath [1]:
			self.msg.add(f'mergerom: {sourcepath[0]}', 'File is not present', spool='error')
			return
		sourcepath = sourcepath.file
		sourcezip = zipfile.ZipFile(sourcepath, mode='r')
		mergezip  = zipfile.ZipFile(self.dest.file, mode='a')
		if len (tomerge) > 0:
			for i in tomerge:
				sourcezip.extract (i, path=tmppath)
				mergezip.write(os.path.join(tmppath,i),i)
				print (f"Added {i} device file to rom.")
			sourcezip.close()
			mergezip.close()
			shutil.rmtree(tmppath)
		return True

	def __fileromset__ (self, romname, table, field):
		""" Returns a set of fileroms the Database, tables of roms, devices or disks
			"""
		
		if self.name != None:
			data = self.con.execute (f"SELECT {field} FROM {table} WHERE name = '{romname}' ")
			if data != None:
				myset = set()
				for i in data:
					myset.add(i[0])	
				return myset
		return set ()
	
	def __filezipromset__ (self, filezip):
		""" Returns a set of files contained into the zip file
			"""
		if itemcheck (filezip) != 'file':
			return False
		a = zipfile.ZipFile(filezip, mode='r').namelist()
		if a != None:
			return set (a)
		return set ()

	def __sha1__ (self, filepath):
		""" Returns the sha1 digest of the file
			"""
		hasher = sha1()
		with open( filepath, 'rb') as afile:
			buf = afile.read()
			hasher.update(buf)
		return (hasher.hexdigest())

	def __checkSHA1__ (self, file, table, romfield, hashfield):
		""" Checks sha1 chekcum for a file and compares it with the value at the database.
			file: 	path of your file at the harddisk
			table:	table at SQL to retrieve the value
			romfield: field at the SQL to match the file name
			hashfield: field at the SQL to retrieve the sha1 value
			"""
		file_name = os.path.basename(file)

		if table == 'disks':
			file_name = os.path.splitext(file_name)[0] # removes trail .chd

		sqldigest  = self.con.execute (f"SELECT {hashfield} FROM {table} WHERE name = '{self.name}' AND {romfield} = '{file_name}'").fetchone()
		if sqldigest == None:
			return True
		if sqldigest[0]==None:
			self.msg.add(file_name, f"\tsha1 not found on Database: {file}")
			return True
		if itemcheck (file) == 'file':
			filename = os.path.basename(file)
			filedigest = self.__sha1__(file)
			if filedigest == sqldigest[0]:
				print (f"{self.name}\tsha1 OK: {filename}")
			else:
				self.msg.add(filename, f"\tsha1 do not match, game may not work: {file}", spool='error')
		else:
			self.msg.add(file, f"\tfile does not exist: {file}", spool='error')

	def __checkCHDsSHA1__ (self):
		""" Checks CHDs files at romset
			"""
		# For CHDs
		for file in self.__CHDsfiles__():
			self.__checkSHA1__(file, 'disks', 'dsk_name', 'dsk_sha1')

	def __checkROMsSHA1__ (self):
		checked = []  # is a list of already checked file-roms.
		if self.origin.exists:
			a = zipfile.ZipFile(self.origin.file, mode='r')
			rtmppath = os.path.join(tmppath,self.name)
			a.extractall(rtmppath)
			romlistzip = self.__filezipromset__(self.origin.file)
			romlist = self.__fileromset__(self.name,'roms','rom_name')
			extrafiles = dict()  # extra files that are at ZIP file but not in Database
			for ef in romlistzip.difference(romlist):
				extrafiles [ef] = self.__sha1__(os.path.join(rtmppath,ef))
			for r in romlist:
				if r in checked:
					continue
				if r not in list(romlistzip) and self.romof is not None:
					rchecked, xtraf, msg = Rom (self.con, self.romof).__checkROMsSHA1__()
					checked += rchecked	# Returns a list of already checked roms
					extrafiles.update(xtraf)
					self.msg.mix(msg)	# Returning messages, merging them to msg object
					continue
				sqldigest  = self.con.execute (f"SELECT rom_sha1 FROM roms WHERE name = '{self.name}' AND rom_name = '{r}'").fetchone()[0]
				if r in romlistzip:
					self.__checkSHA1__(os.path.join(rtmppath,r), 'roms', 'rom_name', 'rom_sha1')
				elif sqldigest in extrafiles.values():
					self.msg.add(r,f"Rom exists, but with other name")
				else:
					romstatus = self.__romstatus__ (r)
					if romstatus == None:
						self.msg.add(r, "Rom not present at zip file", spool='error')
					else:
						self.msg.add(r, f"Rom not present at zip file: rom with {romstatus} status : (Warning)",)	
				checked.append (r)
		else:
			self.msg.add('ROM ZIP', f'File rom in ZIP not found {self.name}', spool='error')
		return checked, extrafiles, self.msg

	def __romstatus__ (self, rom_name):
		""" Returns rom_status field for a rom on a romset, it is intended to discard error on this roms.
			"""
		status = self.con.execute (f"SELECT rom_status FROM roms WHERE name='{self.name}' AND rom_name = '{rom_name}'").fetchone()[0]
		return status

	def __deviceslist__ (self):
		"""a list of devices for this rom
			"""
		cursor = self.con.execute (f"SELECT dev_name FROM devs WHERE name = '{self.name}'")
		dlist = list()
		for r in cursor:
			dlist.append(r[0])
		if dlist == []:
			return None
		return dlist

	def __checkdevices__ (self):
		""" Check content of devices roms in .zip file for this rom.
			"""
		for d in self.devices:
			msg = Rom(self.con, d).checkrom()
			self.msg.mix(msg)
	
	def checkrom (self):
		""" Checks rom integrity at the romset
			Checks for the SHA1 for the files, bios and parents games.
			"""
		if self.name == None or not self.hasroms:
			return self.msg
		self.msg = Messages(self.name)
		print (f"Checking rom files for {self.name}")
		
		# RomZIPfile
		if self.origin.exists:
			# Rom file is at the Romset folder
			print (('>Checking roms:'))
			self.__checkROMsSHA1__()
			if itemcheck (tmppath) == 'folder': 
				shutil.rmtree(tmppath)
		else:
			self.msg.add('ZIP file at Romset', 'There is no ZIP file for this rom', spool='error')

		# CHDs
		if len (self.__CHDsfiles__()) > 0:
			print ('>Checking CHDs:')
			self.__checkCHDsSHA1__()

		# Devices
		if self.devices != None:
			print ('>Checking devices:')
			self.__checkdevices__()
			
		self.msg.Resumelist(notice=f"====Resume for {self.name}====")
		print ("="*30)
		return self.msg

	def __identifile__ (self, path, fileext):
		filelist = glob(os.path.join(path,self.name + fileext))
		if len (filelist) > 0:
			return os.path.join(filelist[0])
		return None

	def __addstuff__ (self):
		""" Adds stuff to the correspondent rom:
			snaps
			cheats
			samples
			"""
		for i in self.stuff:
			originpath, destpath, filetype = self.stuff[i]
			# Overriding inexistent origin folders
			if originpath == None:
				continue
			# Overriding games with no samples 
			if i == 'samples' and len (self.__fileromset__(self.name, i, 'spl_name')) == 0:
				continue
			unzip = False
			print (f"{self.name} attaching {i}")
			origin = self.__identifile__(originpath, filetype)
			if origin == None:
				origin = os.path.join(originpath,os.path.basename(originpath))+'.zip' # search for a zip file
				if itemcheck (origin) == 'file':
					ziplist = self.__filezipromset__(origin)
					element = self.name + filetype
					if element in ziplist:
 						unzip = True
					else:
						self.msg.add(f"{i}","No file found for the game")
						continue	
				else:
					self.msg.add(f"{i}","No file found for the game")
					continue
			dest = os.path.join(destpath, os.path.basename(origin))
			if itemcheck (dest) == 'file':
				self.msg.add(f'{i}',f"file already exist")
				continue
			if itemcheck (destpath) != "folder":
				os.mkdir(destpath)
			if unzip:
				zipfile.ZipFile(origin, mode='r').extract(element, destpath)
			else:
				shutil.copyfile (origin, dest)
	
	def __removestuff__(self):
		""" Removes rom Stuff form the custom roms library
			"""
		for i in self.stuff:
			originpath, destpath, filetype = self.stuff[i]
			dest = self.__identifile__(destpath, filetype)
			if dest != None:
				if itemcheck (dest) == 'file':
					self.msg.add(i, "Deleted")
					os.remove(dest)

class Romset:
	def __init__ (self, con):
		""" Represents the romset at the database
			"""
		self.con = con						# connection to SQLite3 Database
		self.myCSVfile = os.path.join(crsetpath,"gamelist.csv")		
		self.availableactions = ("add","remove","check")

	def games2csv(self):
		""" Generates a CSV file with the gamelist based on filters.
			By default, without bios, or clones.
			Filename: gamelist.csv
			"""
		if itemcheck (self.myCSVfile) == 'file':
			print (f"There is already a game list: ({self.myCSVfile}).")
			r = input ("I will replace it, do you want to continue? (y/n)")
			if r.lower() not in ('y','yes'):
				print ("Proccess cancelled.")
				return
		if itemcheck (crsetpath) != "folder":
			os.mkdir (crsetpath)
			# For CSV generation and read
		addedcolumns = ['action']
		retrievefields = [	# Fields to retrieve from the DB.Table games
							'name',
							'description',
							'cloneof',
							'chd',
							'year',
							'manufacturer',
							'display_type',
							'display_rotate',
							'driver_savestate',
							'driver_emulation',
							'isbios',
							'isdevice',
							'input_players',
							'input_buttons',
							'input_coins',
							'controls_ctrl_type',
							]
		if Bestgames(self.con).isINdatabase:
			retrievefields += [Bestgames(self.con).scorefield]
		if Catver(self.con).isINdatabase:
			retrievefields += [Catver(self.con).catverfield]
		headerlist = addedcolumns + retrievefields

		#datadict = dict (list(zip(headerlist,['']*len(headerlist))))
		retrievefields_comma = ','.join(retrievefields)	# for SQL Search
		cursor = self.con.execute (f'SELECT {retrievefields_comma} FROM \
						games LEFT JOIN \
		(SELECT name as dk_name, "yes" as chd from disks GROUP BY name) \
						ON games.name = dk_name \
							WHERE (		isbios is False \
									AND isdevice is False  \
									AND ismechanical is False \
									)'
								)
		with open(self.myCSVfile, 'w', newline='') as csvfile:
			writer = csv.writer (csvfile, dialect='excel-tab')
			writer.writerow (headerlist)
			for r in cursor:
				data = [''] + list(r)
				writer.writerow (data)
		print ("Done.")
		print (f"You can edit {self.myCSVfile} file with a spreadsheet and set actions on 'action' column.")
		a = ", ".join(self.availableactions[:-1]) + " and " + self.availableactions[-1]
		print ("Available actions are: ", a)

	def __check_gamelist__ (self):
		if itemcheck (self.myCSVfile) != 'file':
			print (f"There is no game list: ({self.myCSVfile}).")
			r = input ("do you want to generate one? (y/n)")
			if r.lower() in ('y','yes'):
				self.games2csv()
				return True
			else:
				return False
		return True
	
	def processCSVlist (self):
		""" Proccess CSV file with the gamelist and searchs and execute actions.
			actions are stored as text on 'action' column, and for now current actions are:
				add		: to add a game from the romset to the custom rom folder
				delete	: to delete a game-rom from the custom rom folder.
				check	: to check a rom-game files, chds, integrity.
			"""
		# Checking if gamelist file exists
		if not self.__check_gamelist__():
			return
		# process CSV
		csvtmpfile = self.myCSVfile + '.tmp'
		with open (self.myCSVfile, 'r', newline='') as csvfile:
			reader = csv.DictReader (csvfile, dialect='excel-tab')
			with open (csvtmpfile, 'w', newline='') as tmp:
				writer = csv.DictWriter(tmp, reader.fieldnames, dialect='excel-tab')	# Outtput file
				line = 0
				for r in reader:
					line += 1
					if line == 1:
						writer.writeheader()
						continue
					datadict = r
					postkey = None
					if datadict ['action'].lower() in self.availableactions:
						postkey = self.__dofileaction__ (datadict['action'].lower(), datadict['name'])
						print (f"{datadict['name']}: {postkey}")
						datadict ['action'] = postkey
					writer.writerow (rowdict=datadict)
		os.remove (self.myCSVfile)
		shutil.move	(csvtmpfile, self.myCSVfile)
		print ("Done!")

	def __dofileaction__ (self, action, romname):
		if action == 'add':
			msg = Rom (self.con, romname).copyrom()
			if msg.success:
				return 'added'
			return 'error'
		if action == 'remove':
			msg = Rom (self.con, romname).removerom()
			if msg.success:
				return 'deleted'
			return 'error'
		if action == 'check':
			msg = Rom (self.con, romname).checkrom()
			if msg.success:
				return 'checked-OK'
			return 'checked-ERROR'
		return

	def chooserom (self):
		""" Choose a rom name from the database iterating a list of possible candidates.
		Or by giving its unique name.
			"""
		candidate = True
		options = dict ()
		opclones = {1: ' cloneof is NULL AND ', -1 : ''}
		opclones_st = 1
		while True:
			print ('\t(commands and active filters:)')
			print ('\t/clones','\t', opclones[opclones_st])
			print ('-'*30)
			print ('Enter a rom-name, or a word in his description, or a number in the list, press enter to exit')
			candidate = input ('find a rom by name: ')
			if candidate == "":
				return False
			if candidate == "/clones":
				opclones_st *= -1
				print (opclones[opclones_st])
			if str(candidate) in options.keys():
				print (f'Selected: {options[candidate]}')
				return options[candidate]
			oneshot = self.con.execute (f"SELECT name, description FROM games WHERE \
						name=?", (candidate,)).fetchone()
			if oneshot is not None:
				return oneshot[0]
			print ("\n"*2, f">> searching {candidate}>>")
			cursor = self.con.execute (f"SELECT name, description FROM games WHERE \
						{opclones[opclones_st]} \
						isdevice IS FALSE AND \
						isbios IS FALSE AND \
						description LIKE '%?%'", (candidate,)
						)
			options = dict ()
			counter = 0
			for i in cursor:
				counter += 1
				options [str(counter)] = i[0]
				print (f'{counter:<3} - {i[0]}\t,{i[1][:80]}')
			if counter == 0:
				print ("No candidates found, try to enter a word on his description.")
	
	def Updatecsv (self):
		""" Update gamelist.csv with the roms in your custom ROMs folder
			Just cleans 'action' column and put 'Have' on the games that you have in your custom rom folder.  
			"""
		msg = Messages('Custom Roms folder')
		# Checking if gamelist file exists
		if not self.__check_gamelist__():
			msg.add('UpdateCSV','There is no CSV file', spool='error')
			return msg
		# process CSV
		csvtmpfile = self.myCSVfile + '.tmp'
		with open (self.myCSVfile, 'r', newline='') as csvfile:
			reader = csv.DictReader (csvfile, dialect='excel-tab')
			with open (csvtmpfile, 'w', newline='') as tmp:
				writer = csv.DictWriter(tmp, reader.fieldnames, dialect='excel-tab')	# Outtput file
				line = 0
				for r in reader:
					line += 1
					if line == 1:
						writer.writeheader()
						continue
					datadict = r
					game_rom = r['name']
					if itemcheck (os.path.join(romspath, game_rom + romsext)) == 'file':
						datadict['action']='Have'
						print (line, 'Have', game_rom)						
					else:
						datadict['action']=''
					writer.writerow (rowdict=datadict)
		os.remove (self.myCSVfile)
		shutil.move	(csvtmpfile, self.myCSVfile)
		print ("Done!")
		return msg

class Bestgames:
	""" Best games list by progetto, adds a score to the roms.
		https://www.progettosnaps.net/bestgames/
		current functions:
		Adds registry to database.
		"""	
	def __init__(self, con):
		self.msg = Messages ('Bestgames')
		self.con = con
		self.scorefield = 'score'
		self.isINdatabase = checkfield(con, self.scorefield)
		self.bgfile = 'bestgames.ini'
		if itemcheck (self.bgfile) != 'file':
			self.msg.add('bestgames.ini','file not found, you can download it from:\nhttps://www.progettosnaps.net/bestgames/', spool='error')
			self.fileexists = False
		else:
			self.fileexists = True

	def addscores (self):
		if not self.fileexists:
			return self.msg
		if not self.isINdatabase:
			# Adding score field to table
			self.con.execute (f"ALTER TABLE games ADD {self.scorefield} char")
			self.con.commit()
			self.isINdatabase = True
		#Reading and updating data:
		pscorelist = [
				"[0 to 10 (Worst)]",
				"[10 to 20 (Horrible)]",
				"[20 to 30 (Bad)]",
				"[30 to 40 (Amendable)]",
				"[40 to 50 (Decent)]",
				"[50 to 60 (Not Good Enough)]",
				"[60 to 70 (Passable)]",
				"[70 to 80 (Good)]",
				"[80 to 90 (Very Good)]",
				"[90 to 100 (Best Games)]",
				]
		pscorelist.reverse()
		# processing bestgames.ini file.
		with open (self.bgfile, "r") as inifile:
			value = pscorelist.pop()
			next = pscorelist[-1]
			readable = False
			commitcounter = 0
			commitevery = 1000
			for line in inifile:
				i = line[:-1]
				if i == value:
					readable = True
					continue
				if i == next:
					value = pscorelist.pop()
					if len (pscorelist)>0:
						next = pscorelist[-1]
					continue
				if readable and i != "":
					self.con.execute (f"UPDATE games SET {self.scorefield}=? WHERE name=?", (value,i,))
					commitcounter += 1
					if commitcounter % commitevery == 0:
						self.con.commit ()
			self.con.commit()
		print (f"Database updated with {self.bgfile}")

class Catver:
	""" Category / Version list, adds a catver field for the game table
		download latest catver.ini from Mamedats at
		https://www.progettosnaps.net/catver/
		current functions:
		Adds registry to database.
		"""
	def __init__ (self, con):
		self.msg = Messages ('catver.ini')
		self.con = con
		self.catverfield = 'catver'
		self.catverfile = 'catver.ini'
		self.isINdatabase = checkfield(con, self.catverfield)
		if itemcheck (self.catverfile) != 'file':
			self.msg.add('catver.ini','file not found, you can download it from:\nhttps://www.progettosnaps.net/catver/', spool='error')
			self.fileexists = False
		else:
			self.fileexists = True

	def addcatver(self):
		""" Read catver.ini file and adds information to the database
			"""
		if not self.fileexists:
			return self.msg
		if not self.isINdatabase:
			# Adding score field to table
			self.con.execute (f"ALTER TABLE games ADD {self.catverfield} char")
			self.con.commit()
			self.isINdatabase = True
		#Removing error on parsing lines (working on a .tmp file)
		with open (self.catverfile, "r") as inifile:
			with open (self.catverfile + '.tmp', "w") as newinifile:
				for line in inifile:
					if "=" in line or "[" in line:
						newinifile.write (line)	
		
		#Reading and updating data:
		catver = configparser.ConfigParser()
		catver.read (self.catverfile + '.tmp')
		if 'Category' not in catver.sections():
			msg.add('[Category] section','No category section found', spool='error')
			return msg
		cursor = self.con.execute ("SELECT name FROM games")
		commitcounter = 0
		commitevery = 1000
		for i in cursor:
			game = i[0]
			if game in catver['Category']:
				self.con.execute (f"UPDATE games SET {self.catverfield}=? WHERE name=?", (catver['Category'][game], game))
			commitcounter += 1
			if commitcounter % commitevery == 0:
				self.con.commit ()
		self.con.commit()
		os.remove(self.catverfile+'.tmp')
		print (f"Database updated with {self.catverfile}")

if __name__ == '__main__':
	########################################
	# Retrieve cmd line parameters
	########################################
	print ("mameXML2SQLite3 v", __version__, "by", __author__)

	parser = argparse.ArgumentParser()

	parser.add_argument("-x", "--xml", default=os.path.join(rsetpath,"mame.xml"),
						help="xml file path. xml romset file.")
	parser.add_argument("-s", "--romset", default=os.path.join(rsetpath,"roms"),
						help="romset folder path. Contains all mame romset.")
	parser.add_argument("-c", "--chds", default=os.path.join(rsetpath,"chds"),
						help="chds folder path. A folder where your romset CHDs are.")
	parser.add_argument("-ch", "--cheat", default=os.path.join(rsetpath, "cheat"),
						help="cheat folder")
	parser.add_argument("-sm", "--samples", default=os.path.join(rsetpath,"samples"),
						help="samples folder")
	parser.add_argument("-sn", "--snap", default=os.path.join(rsetpath,artworkpath,"snap"),
						help="artwork snap folder")
	parser.add_argument("-r", "--customromset", default=crsetpath,
						help="Your custom rom folder. There will go your custom set of games-roms and stuff")


	args = parser.parse_args()

	# Retrieving variables from args
		# defaults on custom romset dir
	crsetpath	= args.customromset
	romspath	= os.path.join(crsetpath,"roms")
		# defaults on romset dir
	romsetpath	= args.romset
	xmlfile		= args.xml
	chdspath	= args.chds
	samplespath	= args.samples
	cheatpath	= args.cheat
			#defaults on romset/mameartwork
	snappath	= args.snap

	# Checking parameters
	errorlist 	= []
	warninglist	= []
	
		# Errors
	if itemcheck(romsetpath)	!= "folder":
		errorlist.append (f"I can't find romset folder:(--romset {romsetpath})")
	if romspath == romsetpath:
		errorlist.append (f'please, place your custom roms path out of your romset folder: {romspath}')

		#Warnings
	if itemcheck(xmlfile) 	!= "file":
		warninglist.append (f"I can't find the xml file:(--xml {xmlfile})")
	if itemcheck(chdspath) 	!= "folder":
		warninglist.append (f"I can't find the chds folder:(--chds {chdspath})")
		chdspath = os.path.join(rsetpath,'chds')
	if itemcheck(cheatpath)	!= "folder":
		warninglist.append (f"I can't find the cheats folder:(--cheat {cheatpath})")
		cheatpath = None
	if itemcheck(samplespath)!= "folder":
		warninglist.append (f"I can't find the sample folder:(--samples {samplespath})")
		samplespath = None
	if itemcheck(snappath) 	!= "folder":
		warninglist.append (f"I can't find the snap folder:(--snap {snappath})")
		snappath = None

	if len (warninglist) > 0:
		for i in warninglist:
			print (i)
	if len (errorlist) > 0:
		errorlist.append ("Please revise errors and try again")
		for i in errorlist:
			print (i)
		exit()

	dbpath = createSQL3(xmlfile)	# Creating or load an existent SQLite3 Database
	if dbpath:
		con = sqlite3.connect (dbpath)	# Connection to SQL database.
	else:
		print ("Can't find a database, please generate one giving a xml file on the --xml argument.\n")
		exit()

	#  User interface:
	#=====================
	action = True
	while action != "":
		user_options = {
			"1": "Create a bios folder with all bios roms",
			"2": "Search and copy a rom from Romset to custom Roms Folder",
			"3": "Search and remove a rom from the custom Roms Folder",
			"4": "Check a game romset for file integrity (roms and related parents, bios, chds, devices)",
			"5": "Add bestgames.ini information to database",
			"6": "Add catver.ini information to database",
			"7": "Generate a games-list in CSV format (gamelist.csv)",
			"8": "Proccess actions in games-list CSV file (gamelist.csv)",
			"9": "Mark games at your custom roms folder in gamelist.csv",
			"10": "Move all bios files from Custom Romset to Bios folder",
			}
		print ('\n')
		for o in user_options:
			print (f"{o} - {user_options[o]}")
		action = input ("Enter an option, hit enter to exit > ")
		if action == "1":
			Bios(con).copyallbios()
		elif action == "2":
			romname = Romset(con).chooserom ()
			if romname:
				msg = Rom (con, romname).copyrom()
				msg.Resumelist(notice=f"=== Resume for {romname} ===")
		elif action == "3":
			romname = Romset(con).chooserom ()
			if romname:
				msg = Rom (con, romname).removerom()
				msg.Resumelist(notice=f"=== Resume for {romname} ===")
		elif action == "4":
			romname = Romset(con).chooserom ()
			if romname:
				Rom (con, romname).checkrom()
		elif action == "5":
			Bestgames (con).addscores()
		elif action == "6":
			Catver (con).addcatver()
		elif action == "7":
			Romset (con).games2csv()
		elif action == "8":
			Romset (con).processCSVlist()
		elif action == "9":
			Romset (con).Updatecsv()
		elif action == "10":
			Bios(con).movebios()
		elif action == "":
			print ("Done!")
			exit ()
		else:
			print ("\n"*4)
			print ("unknown action, please enter a number")
