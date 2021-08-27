#!/usr/bin/python3
# -*- encoding: utf-8 -*-

__version__ = "0.4"
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
import os, argparse, sqlite3, re, shutil, zipfile, csv
from hashlib import sha1
from glob import glob

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
artworkpath	= 'mame artwork'
tmp			= 'tmp'


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

def printlist (mylist):
	for i in mylist:
		print (i)

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

	
	def mix (self, msg):
		""" Mixes another msg spool object into this
			"""
		for i in msg.Wmsg:
			self.add(msg.name,f"({' : '.join(list(i))})")
		for i in msg.Emsg:
			self.add(msg.name,f"({' : '.join(list(i))})", spool='error')

def createSQL3 (xmlfile):
	### Wich tags are retrieved from XML
	# There are 3 tables: 
	# 	one table for game information 		(there is only one value for the game)
	#	one table for file rom information	(there are some values for a game)
	#	one table for device rom information(there are some values for a game)
	#	one table for damples rom information(there are some values for a game)

	# for Gametable, define which tags contains attributes to fetch
	# it will find attributes in this tags: <tag attribute=value/>
	gtTagg = ("game","display","driver")
	# for Gametable, define which tags contains Text to fetch
	# it will find this tags and retrieve their text value : <tag>text</tag>
	gtTxt  = ("description","year","manufacturer")

	gamefields = {
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
		}

	gamefields_type = {
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
		}

	# for Rom Table, define which tags contains attributes to fetch
	rtTagg = ("rom",)

	romsfields = {
			"name": None,
			"size": None,
			"crc": None,
			"sha1": None,
			"status": None ,
			"optional": None,
		}
	romsfields_type = {
			"name": 			("rom_name"			,"char", "NOT NULL"),
			"size": 			("rom_size"			,"int" , ""),
			"crc":	 			("rom_crc"			,"char", ""),
			"sha1": 			("rom_sha1"			,"char", ""),
			"status":			("rom_status"		,"char", ""),
			"optional":			("rom_optional"		,"char", ""),
		}

	# for device Table, define which tags contains attributes to fetch
	dtTagg = ("device_ref",)

	devsfields = 		{"name": None,}
	devsfields_type = 	{"name":	("dev_name", "char", "NOT NULL"),}	

	# for disks Table, define which tags contains attributes to fetch
	ktTagg = ("disk",)
	
	diskfields = 		{
						"name": None,
						"sha1": None,
						"region": None,
						"index" : None,
						"writable": None,
						}
	diskfields_type = 	{
						"name":		("dsk_name", "char", "NOT NULL"),
						"sha1": 	("dsk_sha1", "char", ""),
						"region":	("dsk_region", "char", ""),
						"index":	("dsk_index", "char", ""),
						"writable":	("dsk_writable", "char", ""),
						}	

	# for samples Table, define which tags contains attributes to fetch
	spTagg = ("sample",)

	splsfields = 		{"name": None,}
	splsfields_type = 	{"name":	("spl_name", "char", "NOT NULL"),}	


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

	class Game:
		def __init__ (self,con):
			self.con = con
			# Init game and roms data table fields
			self.gf 	= gamefields.copy ()
			self.__rf__ = romsfields.copy ()
			self.__df__ = devsfields.copy ()
			self.__kf__ = diskfields.copy ()
			self.__sp__ = splsfields.copy ()
			self.rflist = []
			self.dflist = []
			self.kflist = []
			self.splist = []
			
		def __datatypeparser__ (self):
			""" Parses internal string retrieved data into its correct type
				"""
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
			for i in gamefields_type:
				if gamefields_type[i][1] == 'int':
					self.gf[i] = int(self.gf[i])
				elif gamefields_type[i][1] == 'bool':
					self.gf[i] = tobool (self.gf[i])
			# for roms data
			newlist = []
			for j in self.rflist:
				newdict = j[1].copy()
				for i in romsfields_type:
					if romsfields_type[i][1] == 'int':
						newdict[i] = int(newdict[i])
					elif romsfields_type[i][1] == 'bool':
						newdict[i] = tobool(newdict[i])
				newlist.append ((j[0],newdict))
			self.rflist = newlist.copy()
			# for devs data
			newlist = []
			for j in self.dflist:
				newdict = j[1].copy()
				for i in devsfields_type:
					if devsfields_type[i][1] == 'int':
						newdict[i] = int(newdict[i])
					elif devsfields_type[i][1] == 'bool':
						newdict[i] = tobool(newdict[i])
				newlist.append ((j[0],newdict))
			self.dflist = newlist.copy()

		def adddata (self,data):
			""" adds data for the game, data is a tuple from the XML extractor, (see Readxmlline class)
			(tagg, attr,text )
				"""
			# adding GameTable with attributes taggs
			if data[0] in gtTagg and data[1]!=None:
				# reading attr from input dict
				for i in gamefields:
					if i in data[1]:
						self.gf[i] = data[1].get(i)
			# adding GameTable Tag with text
			if data[0] in gtTxt:
				self.gf[data[0]]=data[2]
			# adding RomTable with attributes taggs
			if data[0] in rtTagg and data[1]!=None:
				# reading attr from input dict
				for i in romsfields:
					if i in data[1]:
						self.__rf__[i] = data[1].get(i)
				self.rflist.append ((self.gf['name'], self.__rf__.copy() ))
			# adding devTable with attributes taggs
			if data[0] in dtTagg and data[1]!=None:
				# reading attr from input dict
				for i in devsfields:
					if i in data[1]:
						self.__df__[i] = data[1].get(i)
				self.dflist.append ((self.gf['name'], self.__df__.copy() ))
			# adding dskTable with attributes taggs
			if data[0] in ktTagg and data[1]!=None:
				# reading attr from input dict
				for i in diskfields:
					if i in data[1]:
						self.__kf__[i] = data[1].get(i)
				self.kflist.append ((self.gf['name'], self.__kf__.copy() ))
			# adding splTable with attributes taggs
			if data[0] in spTagg and data[1]!=None:
				# reading attr from input dict
				for i in splsfields:
					if i in data[1]:
						self.__sp__[i] = data[1].get(i)
				self.splist.append ((self.gf['name'], self.__sp__.copy() ))
		
		def write2db (self):
			""" Write data to Database
				"""
			self.__datatypeparser__()
			# game table:
			fields = ",".join([gamefields_type[i][0] for i in self.gf])
			values = [i for i in self.gf.values()]
			questions = ",".join("?"*len(self.gf))
			con.execute(f"INSERT INTO games ({fields}) VALUES ({questions})", values)
			# roms table
			for r in self.rflist:
				fields = ",".join([romsfields_type[i][0] for i in r[1]]) + ",name"
				values = [i for i in r[1].values()]
				values.append (r[0]) # append key field with game name to the list
				questions = ",".join("?"*len(r[1])) + ",?"
				con.execute(f"INSERT INTO roms ({fields}) VALUES ({questions})", values)
			# devs table
			for r in self.dflist:
				fields = ",".join([devsfields_type[i][0] for i in r[1]]) + ",name"
				values = [i for i in r[1].values()]
				values.append (r[0]) # append key field with game name to the list
				questions = ",".join("?"*len(r[1])) + ",?"
				con.execute(f"INSERT INTO devs ({fields}) VALUES ({questions})", values)
			# disk table
			for r in self.kflist:
				fields = ",".join([diskfields_type[i][0] for i in r[1]]) + ",name"
				values = [i for i in r[1].values()]
				values.append (r[0]) # append key field with game name to the list
				questions = ",".join("?"*len(r[1])) + ",?"
				con.execute(f"INSERT INTO disks ({fields}) VALUES ({questions})", values)
			# samples table
			for r in self.splist:
				fields = ",".join([splsfields_type[i][0] for i in r[1]]) + ",name"
				values = [i for i in r[1].values()]
				values.append (r[0]) # append key field with game name to the list
				questions = ",".join("?"*len(r[1])) + ",?"
				con.execute(f"INSERT INTO samples ({fields}) VALUES ({questions})", values)

	# Checking and initializing the Database
	########################################
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
	tablefields = ",".join( [i[0]+" "+i[1]+" "+i[2] for i in gamefields_type.values()]) 
	cursor.execute (f'CREATE TABLE games ({tablefields})')
	# roms table
	tablefields = "name, " + ",".join( [i[0]+" "+i[1]+" "+i[2] for i in romsfields_type.values()]) 
	cursor.execute (f'CREATE TABLE roms ({tablefields})')
	# devs table
	tablefields = "name, " + ",".join( [i[0]+" "+i[1]+" "+i[2] for i in devsfields_type.values()]) 
	cursor.execute (f'CREATE TABLE devs ({tablefields})')
	# disk table
	tablefields = "name, " + ",".join( [i[0]+" "+i[1]+" "+i[2] for i in diskfields_type.values()]) 
	cursor.execute (f'CREATE TABLE disks ({tablefields})')
	# sample table
	tablefields = "name, " + ",".join( [i[0]+" "+i[1]+" "+i[2] for i in splsfields_type.values()]) 
	cursor.execute (f'CREATE TABLE samples ({tablefields})')
	con.commit()

	fh = open(xmlfile)
	gamecount = 0
	game = Game(con)
	print ("Scanning XML and poblating database")
	for i in fh:
		line = Readxmlline(i)
		game.adddata(line.data())
		if line.clos and line.tagg == 'game':
			# Closing current game and writting data to Database
			game.write2db() # write game to db
			gamecount += 1
			print (f"{gamecount}: {game.gf['name']}")
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
	fullfilepath = os.path.join(path,file + romsext) 
	if itemcheck (fullfilepath) == 'file':
		return (fullfilepath, True)
	return (fullfilepath, False)

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
		self.msg.Emsglist()

	def copybios (self,biosname):
		""" copy a bios from romset to bios folder
			"""
		origin 	= check (biosname, romsetpath)
		dest 	= check (biosname, biospath)
		if origin[1] == False:
			self.msg.add ({biosname},"bios is not present at romset",spool='error')
			return
		if dest[1] == True:
			self.msg.add ({biosname},"bios already exist on bios folder",spool='error')
			return
		shutil.copyfile (origin[0], dest[0])

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
		romheads = con.execute (f'SELECT name,cloneof,romof, isbios FROM games WHERE name = "{romname}"').fetchone()
		if romheads == None:
			#print (f'Thereis no rom-game called {romname}')
			self.msg.add('XML',f'Thereis no rom-game called {romname}', spool = 'error')
			self.name 	= None
			self.origin = (None, None)
			self.dest 	= (None, None)
			self.maingame, self.bios = None, None
		else:
			self.name, self.cloneof, self.romof, self.isbios = romheads
			self.origin	= check (romname, romsetpath)
			self.dest 	= check (romname, romspath)
			self.maingame, self.bios = self.__maingame__ ()
			self.devices = self.__deviceslist__()

	def removerom (self):
		""" removes a rom file from the custom rom folder
			"""
		self.msg = Messages(self.name)
		if self.name == None:
			return
		if self.dest[1]:
			os.remove (self.dest[0])
			print (f'{self.name} : deleted')
		else:
			self.msg.add (f'{self.name}:Rom ZIP',"File is not at your custom Rom folder")
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
			if self.isbios:
				Bios (con).copybios(self.name)
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
		if self.origin[1] == False:
			self.msg.add('Rom at romset',f"{self.name} file is not present",spool='error')
			return
		if self.dest[1] == True:
			self.msg.add('Rom at romset',f"{self.name} file already exist")
			return
		shutil.copyfile (self.origin[0], self.dest[0])
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
			dest = os.path.join (romspath, self.maingame, file)
			chdgamedir = os.path.join (romspath, self.maingame)
			if itemcheck (origin) != 'file':
				self.msg.add('CHD',f'CHD not found: {origin}', spool='error')
				return False
			if itemcheck (chdgamedir) != 'folder':
				os.mkdir (chdgamedir)
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
		if devromset in zipfileset:
			self.msg.add (f'roms in {self.dest[0]}',"files are already in the zip file")
			return
		tomerge = devromset.difference(zipfileset)
		sourcepath = check (source, romsetpath)
		if not sourcepath [1]:
			self.msg.add(f'mergerom: {sourcepath[0]}', 'File is not present', spool='error')
			return
		sourcepath = sourcepath[0]
		sourcezip = zipfile.ZipFile(sourcepath, mode='r')
		mergezip  = zipfile.ZipFile(self.dest[0], mode='a')
		if len (tomerge) > 0:
			for i in tomerge:
				sourcezip.extract (i, path='tmp')
				mergezip.write(os.path.join('tmp',i),i)
				print (f"Added {i} device file to rom.")
			sourcezip.close()
			mergezip.close()
			shutil.rmtree('tmp')
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
		if itemcheck (file) == 'file':
			filename = os.path.basename(file)
			filedigest = self.__sha1__(file)
			if filedigest == sqldigest[0]:
				print (f"{self.name}\tsha1 OK: {filename}")
			else:
				self.msg.add(filename, "\tsha1 do not match, game may not work", spool='error')

	def __checkCHDsSHA1__ (self):
		""" Checks CHDs files at romset
			"""
		# For CHDs
		for file in self.__CHDsfiles__():
			self.__checkSHA1__(file, 'disks', 'dsk_name', 'dsk_sha1')

	def __checkROMsSHA1__ (self):
		checked = []
		a = zipfile.ZipFile(self.origin[0], mode='r')
		romlistzip = self.__filezipromset__(self.origin[0])
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
				extracted = a.extract(r,tmp)
				self.__checkSHA1__(extracted, 'roms', 'rom_name', 'rom_sha1')
				os.remove(os.path.join(tmp,r))
			else:
				romstatus = self.__romstatus__ (r)
				if romstatus != None:
					self.msg.add(r, f"Rom not present at zip file: rom with {romstatus} status",)	
				else:
					self.msg.add(r, "Rom not present at zip file", spool='error')
			checked.append (r)
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
		if self.name == None:
			return
		self.msg = Messages(self.name)
		print (f"Checking files for {self.name}")
		
		# RomZIPfile
		if self.origin [1]:
			# Rom file is at the Romset folder
			print (('Checking roms:'))
			self.__checkROMsSHA1__()
		else:
			self.msg.add('ZIP file at Romset', 'There is no ZIP file for this rom', spool='error')

		# CHDs
		if len (self.__CHDsfiles__()) > 0:
			print ('Checking CHDs:')
			self.__checkCHDsSHA1__()

		# Devices
		if self.devices != None:
			print ('checking devices:')
			self.__checkdevices__()
			
		self.msg.Emsglist(notice='Some errors where ecountered:')
		return self.msg

	def __identifile__ (self, path, fileext):
		filelist = glob(os.path.join(path,self.name + fileext))
		if len (filelist) > 0:
			print (f"Selected: {filelist[0]}")
			return os.path.join(filelist[0])
		return None

	def __addstuff__ (self):
		""" Adds stuff to the correspondent rom:
			snaps
			cheats
			samples
			"""
		stuff = {
				'snap'		: (snappath,	'snap',		'.*'),
				'cheat'		: (cheatpath,	'cheat',	'.xml'),
				'samples'	: (samplespath,	'samples',	'.zip'),
				}
		for i in stuff:
			originpath, destpath, filetype = stuff[i]
			if originpath == None:
				continue
			print (f"attaching {i}")
			origin = self.__identifile__(originpath, filetype)
			if origin == None:
				self.msg.add(f"{i}","No file found for the game")
				continue
			dest = os.path.join(destpath, os.path.basename(origin))
			if itemcheck (dest) == 'fie':
				self.msg.add(f'{i}',f"file already exist")
				continue
			if itemcheck (destpath) != "folder":
				os.mkdir(destpath)
			shutil.copyfile (origin, dest)

class Romset:
	def __init__ (self, con):
		""" Represents the romset at the database
			"""
		self.con = con	# connection to SQLite3 Database
		self.myCSVfile = "gamelist.csv"
		# For CSV generation and read
		self.addedcolumns = ['action']
		self.retrievefields = [	'name',
							'description',
							'cloneof',
							'chd',
							'year',
							'manufacturer',
							'display_type',
							'display_rotate',
							'driver_savestate',
							'driver_emulation',
							'driver_color',
							'driver_sound',
							'driver_graphic',
							]
		if Bestgames(self.con,bgfile).checkfield():
			self.retrievefields += ['score']
		self.headerlist = self.addedcolumns + self.retrievefields

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
		#datadict = dict (list(zip(headerlist,['']*len(headerlist))))
		retrievefields_comma = ','.join(self.retrievefields)	# for SQL Search
		cursor = self.con.execute (f'SELECT {retrievefields_comma} FROM \
						games LEFT JOIN \
		(SELECT name as dk_name, "yes" as chd from disk GROUP BY name) \
						ON games.name = dk_name \
							WHERE (		isbios is False \
									AND isdevice is False  \
									AND ismechanical is False \
									)'
								)
		with open(self.myCSVfile, 'w', newline='') as csvfile:
			writer = csv.writer (csvfile, dialect='excel-tab')
			writer.writerow (self.headerlist)
			for r in cursor:
				data = [''] + list(r)
				writer.writerow (data)
		print ("Done.")
		print (f"You can edit {self.myCSVfile} file with a spreadsheet and set actions on 'action' column.")
		print ("Available actions are: add and remove")

	def processCSVlist (self):
		""" Proccess CSV file with the gamelist and searchs and execute actions.
			actions are stored as text on 'action' column, and for now current actions are:
				add		: to add a game from the romset to the custom rom folder
				delete	: to delete a game-rom from the custom rom folder.
				check	: to check a rom-game files, chds, integrity.
			"""
		if itemcheck (self.myCSVfile) != 'file':
			print (f"There is no game list: ({self.myCSVfile}).")
			r = input ("do you want to generate one? (y/n)")
			if r.lower() in ('y','yes'):
				self.games2csv()
			else:
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
					if datadict ['action'].lower() in ('add','remove', 'check'):
						postkey = self.__dofileaction__ (datadict['action'].lower(), datadict['name'])
					elif datadict ['action'] not in ('added','removed','checked-OK','checked-ERROR','error','unknown action',''):
						postkey = 'unknown action'
					if postkey:
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
			print ('commands and active filters:')
			print ('/clones','\t', opclones[opclones_st])
			print ('-'*30)
			print ('Press enter to exit')
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
	parser.add_argument("-b", "--bios", default="bios",
						help="bios folder path. A folder where only the custom bios are.")
	parser.add_argument("-r", "--roms", default="roms",
						help="roms folder path. Your custom rom folder.")
	parser.add_argument("-c", "--chds", default=os.path.join(rsetpath,"chds"),
						help="chds folder path. A folder where your romset CHDs are.")
	parser.add_argument("-bg", "--bestgames", default="bestgames.ini",
						help="bestgames ini file by progetto.")
	parser.add_argument("-sn", "--snap", default=os.path.join(rsetpath,artworkpath,"snap"),
						help="artwork snap folder")
	parser.add_argument("-ch", "--cheat", default=os.path.join(rsetpath, "cheat"),
						help="cheat folder")
	parser.add_argument("-sm", "--samples", default=os.path.join(rsetpath,"samples"),
						help="samples folder")
						

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
	if itemcheck(romsetpath)	!= "folder":
		errorlist.append (f"I can't find romset folder:(--romset {romsetpath})")

	if itemcheck (bgfile) != "file":
		warninglist.append (f"I can't find bestgames file:(--bestgames {bgfile})")

	if itemcheck(xmlfile) 	!= "file":
		warninglist.append (f"I can't find the xml file:(--xml {xmlfile})")

	if itemcheck(chdspath) 	!= "folder":
		warninglist.append (f"I can't find the chds folder:(--chds {chdspath})")
		chdspath = None
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
		printlist (warninglist)
	if len (errorlist) > 0:
		errorlist.append ("Please revise errors and try again")
		printlist (errorlist)
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
			"4": "Generate a games-list in CSV format (gamelist.csv)",
			"5": "Proccess actions in games-list CSV file (gamelist.csv)",
			"6": "Add bestgames.ini information to database",
			"7": "Check a game romset for file integrity (roms, bios and chds)",
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
				Rom (con, romname).copyrom()
		elif action == "3":
			romname = Romset(con).chooserom ()
			if romname:
				Rom (con, romname).removerom()
		elif action == "4":
			Romset (con).games2csv()
		elif action == "5":
			Romset (con).processCSVlist()
		elif action == "6":
			Bestgames (con, bgfile).addscores()
		elif action == "7":
			romname = Romset(con).chooserom ()
			if romname:
				Rom (con, romname).checkrom()
		elif action == "":
			print ("Done!")
			exit ()
		else:
			print ("\n"*5)
			print ("unknown action, please enter a number")