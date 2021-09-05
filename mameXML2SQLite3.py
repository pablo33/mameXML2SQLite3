#!/usr/bin/python3
# -*- encoding: utf-8 -*-

__version__ = "0.43"
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
	or download XML file from the web.__checkROMsSHA1__

"""

# Standard libray imports
from genericpath import exists
from io import DEFAULT_BUFFER_SIZE
import os, argparse, sqlite3, re, shutil, zipfile, csv
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
class ValueNotExpected(ValueError):
	pass

#=====================================
# Defaults
#=====================================
romsext		= '.zip'
rsetpath 	= 'romset'
artworkpath	= 'artwork'
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
			print ('\n')
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
			print ('\n')

	def Resumelist (self, notice = ''):
		""" Prints a resume of errors / warnings
			"""
		print (notice)
		if len (self.Emsg) > 0:
			self.Emsglist(notice='Errors encountered')
		elif len (self.Wmsg) > 0:
			self.Wmsglist(notice='Warnings encountered')
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

	class Readxmlline:
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
	# There are 5 tables: 
	# 	one table for game information 		(there is only one value for the game)
	#	one table for file rom information	(there are some values for a game)
	#	one table for device rom information(there are some values for a game)
	# 	one table for CHDs (disks) information (there are some CHDs for a game)
	#	one table for samples rom information(there are some values for a game)

	# for each table, define which tags, attrib, text contains data to fetch from the XML
	# it will find attributes in this tags: <tag attribute=value/>  ....  or ....  <tag>text</tag>
	# Also informs if a table is dependant of the main game table.

	if xmlversion <=  162:	
		Table ['games'] = field_table (
			Tagg	=("game","display","driver"),
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
					"color":  			("driver_color"		,"char", ""),
					"sound":  			("driver_sound"		,"char", ""),
					"graphic":  		("driver_graphic"	,"char", ""),
					"savestate":  		("driver_savestate"	,"char", ""),
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
	else:
		Table ['games'] = field_table (
			Tagg	=("machine","display","driver"),
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

	### Checking and initializing the Database
	dbpath = os.path.splitext(xmlfile)[0] + ".sqlite3"

	if itemcheck (dbpath) == 'file':
		print ("Database found, loading it.")
		return (dbpath)
	elif itemcheck (xmlfile) != 'file':
		print ("I can't find xml or associated database. Can't continue")
		exit()
	else:
		print ("Generating a new SQLite database. Be patient.")

	con = sqlite3.connect (dbpath) # it creates one if file doesn't exists
	cursor = con.cursor() # object to manage queries
	# game table
	tablefields = ",".join( [i[0]+" "+i[1]+" "+i[2] for i in Table["games"].Fieldstype.values()])
	cursor.execute (f'CREATE TABLE games ({tablefields})')
	# creating dependant tables
	for t,f in (
			('roms', 	Table["roms"].Fieldstype.values()		),
			('devs', 	Table["devs"].Fieldstype.values()		),
			('disks', 	Table["disks"].Fieldstype.values()		),
			('samples', Table["samples"].Fieldstype.values()	),
			):
		tablefields = "name, " + ",".join( [i[0]+" "+i[1]+" "+i[2] for i in f]) 
		cursor.execute (f'CREATE TABLE {t} ({tablefields})')
	con.commit()

	fh = open(xmlfile)
	gamecount = 0
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
			if (gamecount % 1000) == 0:
				con.commit()
	con.commit()
	con.close()
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

class Bios:
	def __init__(self,con):
		# check if bios folder is present
		self.con = con
		self.msg = Messages ('Bios Set')
		if itemcheck(biospath) != "folder":
			print (f"creating bios folder at: {biospath}")
			os.makedirs (biospath)
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
		dest 	= check (biosname, biospath)
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
			dest	= check (biosname[0], biospath)
			if origin.exists == False:
				continue
			if dest.exists == True:
				self.msg.add (biosname[0],"bios already exist on bios folder")
				os.remove (origin.file)
				continue
			shutil.move (origin.file, dest.file)

class Rom:
	""" Represents a game. It must be in a .zip file
		Methods: 
			copyrom() 	copy this game from romsetfolder to roms folder, 
						also dependant roms if it is a clone and needed bios.
			removerom()	removes a rom from your custom roms folder. bios, or parent games
						remains there.
			checkrom()	Checks all files for the rom to work.

		"""
	def __init__(self,con,romname):
		self.con = con
		self.msg = Messages (romname)
		if itemcheck(romspath) != "folder":
			print (f"creating roms folder at: {romspath}")
			os.makedirs (romspath)
		romheads = self.con.execute (f'SELECT name,cloneof,romof, isbios FROM games WHERE name = "{romname}"').fetchone()
		self.stuff = {
			'snap'		: (snappath,	'snap',		'.*'),
			'cheat'		: (cheatpath,	'cheat',	'.xml'),
			'samples'	: (samplespath,	'samples',	'.zip'),
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
			a romgamepack is formed with rom/clone origin rom, and bios. 
			"""
		self.msg = Messages(self.name)
		if self.name != None:
			self.__copyfile__()
			if self.romof != None:
				msgs = Rom (con, self.romof).copyrom()
				self.msg.mix(msgs) 
			#if self.isbios:
			#	Bios (con).copybios(self.name)
			if self.msg.success:
				self.__adddevs__()
			if self.msg.success:
				self.__addchds__()
				self.__addstuff__()
			self.msg.Emsglist(notice="Something Was wrong, some files were not present.")
		return self.msg

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
		""" Returns a list of fileroms the Database, tables of roms, devices or disks
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
		checked = []
		if self.origin.exists:
			a = zipfile.ZipFile(self.origin.file, mode='r')
			romlistzip = self.__filezipromset__(self.origin.file)
			romlist = self.__fileromset__(self.name,'roms','rom_name')
			for r in romlist:
				if r not in list(romlistzip) and self.romof is not None and r not in checked:
					rchecked, msg = Rom (self.con, self.romof).__checkROMsSHA1__()
					checked += rchecked	# Returns a list of already checked roms
					self.msg.mix(msg)	# Returning messages, merging them to msg object
					continue
				elif r in checked:
					continue
				elif r in romlistzip:
					extracted = a.extract(r,tmppath)
					self.__checkSHA1__(extracted, 'roms', 'rom_name', 'rom_sha1')
					os.remove(os.path.join(tmppath,r))
				else:
					romstatus = self.__romstatus__ (r)
					if romstatus != None:
						self.msg.add(r, f"Rom not present at zip file: rom with {romstatus} status : (Warning)",)	
					else:
						self.msg.add(r, "Rom not present at zip file", spool='error')
				checked.append (r)
		else:
			self.msg.add('ROM ZIP', f'File rom in ZIP not found {self.name}', spool='error')
		return checked, self.msg

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
			Checks for the SHA1 for the files, bios and parents games is it is a clone.
			-TODO: devices
			"""
		if self.name == None or not self.hasroms:
			return self.msg
		self.msg = Messages(self.name)
		print (f"Checking files for {self.name}")
		
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
			
		self.msg.Emsglist(notice='Errors encountered:')
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
				origin = os.path.join(originpath,destpath)+'.zip' # search for a zip file
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
		self.myCSVfile = "gamelist.csv"		
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
							]
		if Bestgames(self.con,bgfile).checkfield():
			retrievefields += ['score']
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
						name = '{candidate}'").fetchone()
			if oneshot is not None:
				return oneshot[0]
			print ("\n"*2, f">> searching {candidate}>>")
			cursor = self.con.execute (f"SELECT name, description FROM games WHERE \
						{opclones[opclones_st]} \
						isdevice IS FALSE AND \
						isbios IS FALSE AND \
						description LIKE '%{candidate}%'"
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
		Checks if there is a score field at database. 
		"""	
	def __init__(self, con, bgfile):
		self.scorefield = 'score'
		self.con = con
		self.bgfile = bgfile
		self.isINdatabase = self.checkfield()
	
	def checkfield (self):
		""" Checks if score field is at database.
			Returns True in case of found it.
			"""
		cursor = self.con.execute ("PRAGMA table_info(games)")
		for i in cursor:
			if i[1] == self.scorefield:
				return True
		return False
	
	def addscores (self):
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
					self.con.execute (f"UPDATE games SET {self.scorefield} = '{value}' WHERE name = '{i}'")
					commitcounter += 1
					if commitcounter % commitevery == 0:
						self.con.commit ()
			self.con.commit()
		print (f"Database updated with {self.bgfile}")

if __name__ == '__main__':
	########################################
	# Retrieve cmd line parameters
	########################################
	
	parser = argparse.ArgumentParser()

	parser.add_argument("-x", "--xml", default="mame.xml",
						help="xml file path. xml romset file.")
	parser.add_argument("-s", "--romset", default=os.path.join(rsetpath,"roms"),
						help="romset folder path. Contains all mame romset.")
	parser.add_argument("-c", "--chds", default=os.path.join(rsetpath,"chds"),
						help="chds folder path. A folder where your romset CHDs are.")
	parser.add_argument("-ch", "--cheat", default=os.path.join(rsetpath, "cheat"),
						help="cheat folder")
	parser.add_argument("-sm", "--samples", default=os.path.join(rsetpath,"samples"),
						help="samples folder")
	parser.add_argument("-b", "--bios", default="bios",
						help="bios folder path. A folder where only the custom bios are.")
	parser.add_argument("-sn", "--snap", default=os.path.join(rsetpath,artworkpath,"snap"),
						help="artwork snap folder")
	parser.add_argument("-r", "--roms", default="roms",
						help="roms folder path. Your custom rom folder.")
	parser.add_argument("-bg", "--bestgames", default="bestgames.ini",
						help="bestgames ini file by progetto.")
						
	args = parser.parse_args()

	# Retrieving variables from args
		# defaults on current dir
	xmlfile		= args.xml
	romsetpath	= args.romset
	biospath	= args.bios
	romspath	= args.roms
	bgfile		= args.bestgames
		# defaults on romset dir
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
	if itemcheck (bgfile) != "file":
		warninglist.append (f"I can't find bestgames file:(--bestgames {bgfile})")
	if biospath == romsetpath:
		errorlist.append (f'please, place bios folder out of your romset folder: {biospath}')
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
		print ("Can't find a database, please specify one with --xml argument.\n")
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
			"6": "Generate a games-list in CSV format (gamelist.csv)",
			"7": "Proccess actions in games-list CSV file (gamelist.csv)",
			"8": "Mark games at your custom roms folder in gamelist.csv",
			"9": "Move all bios files from Custom Romset to Bios folder",
			}
		print ('\n')
		for o in user_options:
			print (f"{o} - {user_options[o]}")
		action = input ("choose an option, hit enter to exit > ")
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
			Bestgames (con, bgfile).addscores()
		elif action == "6":
			Romset (con).games2csv()
		elif action == "7":
			Romset (con).processCSVlist()
		elif action == "8":
			Romset (con).Updatecsv()
		elif action == "9":
			Bios(con).movebios()
		elif action == "":
			print ("Done!")
			exit ()
		else:
			print ("\n"*4)
			print ("unknown action, please enter a number")