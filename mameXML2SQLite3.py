#!/usr/bin/python3
# -*- encoding: utf-8 -*-

__version__ = "0.2"
__author__  = "pablo33"
__doc__		= """
	This software parses a MAME XML file into SQLite3 Database.
	Not all information are parsed. Testing on Romset 1.49
	Copies gamesets from a romset, including bios.
	Copies needed or all bios on a spare bios folder.
	"""

# Standard libray imports
import os, argparse, sqlite3, re, shutil, zipfile, csv

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
rebuildDB 	= False
romsext		= '.zip'

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

def createSQL3 (xmlfile):
	### Wich tags are retrieved from XML
	# There are 3 tables: 
	# 	one table for game information 		(there is only one value for the game)
	#	one table for file rom information	(there are some values for a game)
	#	one table for device rom information(there are some values for a game)

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

	devsfields = {
			"name": None,
		}
	devsfields_type = {
			"name": 			("dev_name"			,"char", "NOT NULL"),
		}	

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
			self.rflist = []
			self.dflist = []
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

	########################################
	# Checking and initializing the Database
	########################################
	dbpath = os.path.splitext(xmlfile)[0] + ".sqlite3"

	if itemcheck (dbpath) == 'file':
		if not rebuildDB:
			print ("Database Found, loading it")
			return (dbpath)
		else:
			os.remove (dbpath)
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
		Todo: also in conbnation of upper and lower case. 
		"""
	fullfilepath = os.path.join(path,file + romsext) 
	if itemcheck (fullfilepath) == 'file':
		return (fullfilepath, True)
	print (f"No se encuentra el fichero {file} en {path}")
	return (fullfilepath, False)

class Bios:
	def __init__(self,con):
		# check if bios folder is present
		self.con = con
		if itemcheck(biospath) != "folder":
			print (f"creating bios folder at: {biospath}")
			os.makedirs (biospath)
	def createbiosfolder (self):
		cursor = self.con.execute ("SELECT name,description FROM games WHERE isbios = 1")
		for b in cursor:
			self.copybios (b[0])

	def copybios (self,biosname):
		""" copy a bios from romset to bios folder
			"""
		origin 	= check (biosname, romsetpath)
		dest 	= check (biosname, biospath)
		if origin[1] == False:
			print (f"{biosname} bios is not present at romset")
			return 
		if dest[1] == True:
			print (f"{biosname} bios already exist on bios folder.")
			return
		shutil.copyfile (origin[0], dest[0])

class Rom:
	""" Represents a game,
		Methods: 
			copyrom: 	copy this game from romsetfolder to roms folder, 
						also dependant roms if it is a clone and needed bios.
		"""
	def __init__(self,con,romname):
		self.con = con
		if itemcheck(romspath) != "folder":
			print (f"creating roms folder at: {romspath}")
			os.makedirs (romspath)
		romheads = con.execute (f'SELECT name,cloneof,romof, isbios FROM games WHERE name = "{romname}"').fetchone()
		if romheads == None:
			print (f'Thereis no rom-game called {romname}')
			self.name 	= None
			self.origin = (None, None)
			self.dest 	= (None, None)
		else:
			self.name, self.cloneof, self.romof, self.isbios = romheads
			self.origin	= check (romname, romsetpath)
			self.dest 	= check (romname, romspath)

	def removerom (self):
		""" removes a rom file from the custom rom folder
			"""
		success = True
		if self.name != None and self.dest[1]:
			os.remove (self.dest[0])
			return success
		return False

	def copyrom (self):
		""" copy a romgame-pack from the romset folder to the roms folder
			a romgamepack is formed with rom/clone origin rom, and bios. 
			TODO: list zip files and fix missing roms and devices.
			"""
		success = True
		if self.name != None:
			success *= self.__copyfile__(self.name)
			if self.romof != None:
				success *= Rom (con, self.romof).copyrom()
			if self.isbios:
				Bios (con).copybios(self.name)
			if success:
				success *= self.__adddevs__(self.name)
			if not success:
				print ("Something Was wrong, some files were not present.")
			return bool (success)
		return False

	def __copyfile__ (self,romname):
		""" copy a romfile to roms folder
			"""
		if self.origin[1] == False:
			print (f"{romname} file is not present at romset")
			return False
		if self.dest[1] == True:
			print (f"{romname} file already exist on roms folder.")
			return True
		shutil.copyfile (self.origin[0], self.dest[0])
		return True

	def __adddevs__ (self,romname):
		"""Adds required devs files to the zipped rom at your cursom rom folder
			"""
		gamedevset 	= self.devset (romname)
		for device in gamedevset:
			return self.__mergerom__(romname,device)
		return True
	
	def __mergerom__ (self, merged, source):
		""" Merge 2 roms. gets zip files from origin rom and put them into dest rom file.
			dest is a rom placed at your custom roms folder
			origin is a rom placed at your romset folder 
			"""
		zipfileset	= self.__filezipromset__ (self.dest[0])
		if zipfileset == False:
			# Zip file doesn't exist
			return False
		devromset 	= self.romset (source)
		if devromset in zipfileset:
			print ("files are already in the zip file")
			return True
		tomerge = devromset.difference(zipfileset)
		sourcepath = check (source, romsetpath)
		if not sourcepath [1]:
			return False
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

	
	def romset (self, romname):
		""" Returns a roms set object from the Database Set of roms
			"""
		if self.name != None:
			data = self.con.execute (f"SELECT rom_name FROM roms WHERE name = '{romname}'").fetchone()
			if data != None:
				return set (data)
		return set ()
	
	def devset (self, romname):
		""" Returns a dev set objetc from the Database Set of roms
			"""
		if self.name != None:
			devices = self.con.execute (f"SELECT dev_name FROM devs WHERE name = '{romname}'").fetchone()
			if devices != None:
				return set (devices)
		return set()
	
	def __filezipromset__ (self, filezip):
		""" Returns a set of files contained into the zip file
			"""
		if itemcheck (filezip) != 'file':
			return False
		a = zipfile.ZipFile(filezip, mode='r').namelist()
		if a != None:
			return set (a)
		return set ()

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
							'year',
							'manufacturer',
							'display_type',
							'display_rotate',
							'driver_savestate',
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
		cursor = self.con.execute (f'SELECT {retrievefields_comma} FROM games \
						WHERE (\
								isbios is False \
							AND isdevice is False \
							AND ismechanical is False \
							AND isdevice is False \
							AND driver_status = "good" \
							AND driver_emulation = "good" \
							AND driver_color = "good" \
							AND driver_sound = "good" \
							AND driver_graphic = "good"\
							)')
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
		with open (csvtmpfile, 'w', newline='') as tmp:
			writer = csv.DictWriter(tmp, self.headerlist, dialect='excel-tab')	# Outtput file
			line = 0
			with open (self.myCSVfile, 'r', newline='') as csvfile:
				reader = csv.DictReader (csvfile, dialect='excel-tab')
				for r in reader:
					line += 1
					if line == 1:
						writer.writeheader()
						continue
					datadict = r
					postkey = None
					if datadict ['action'].lower() in ('add','remove'):
						postkey = self.__dofileaction__ (datadict['action'].lower(), datadict['name'])
					elif datadict ['action'] not in ('added','removed','error','unknown action',''):
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
			success = Rom (self.con, romname).copyrom()
			if success:
				return 'added'
			return 'error'
		if action == 'remove':
			success = Rom (self.con, romname).removerom()
			if success:
				return 'deleted'
			return 'error'
		return 

class Bestgames:
	""" Best games list by progetto, adds a score to the roms.
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
	parser.add_argument("-s", "--romset", default="romset",
						help="romset folder path. Contains all mame romset.")
	parser.add_argument("-b", "--bios", default="bios",
						help="bios folder path. A folder where only the bios are.")
	parser.add_argument("-r", "--roms", default="roms",
						help="roms folder path. Your custom rom folder.")
	parser.add_argument("-bg", "--bestgames", default="bestgames.ini",
						help="bestgames ini file by progetto.")
	

	args = parser.parse_args()

	# Retrieving variables from args
	xmlfile		= args.xml
	romsetpath	= args.romset
	biospath	= args.bios
	romspath	= args.roms
	bgfile		= args.bestgames

	# Checking parameters
	errorlist 	= []
	warninglist	= []
	if itemcheck(xmlfile) 	!= "file":
		errorlist.append (f"I can't find the xml file:(--xml {xmlfile})")

	if itemcheck(romsetpath)	!= "folder":
		errorlist.append (f"I can't find romset folder:(--bios {romsetpath})")

	if itemcheck (bgfile) != "file":
		warninglist.append (f"I can't find bestgames file:(--bestgames {bgfile})")

	if len (warninglist) > 0:
		printlist (warninglist)
	if len (errorlist) > 0:
		errorlist.append ("Please revise errors and try again")
		printlist (errorlist)
		exit()

	dbpath = createSQL3(xmlfile)	# Creating or loading a existent SQLite3 Database
	con = sqlite3.connect (dbpath)	# Connection to SQL database.

	# UseCase: Create the bios folder with a copy of all bios
	# Bios(con).createbiosfolder()

	# UseCase: Copy a rom from romset to rom folder include Bios and fix missing devices
	# Rom (con, "wof").copyrom()
	# Rom (con, "wof").removerom()

	# UseCase: Generate a list of games in CSV (tab-separated)
	# Romset (con).games2csv()
	# Romset (con).processCSVlist()

	# bestgames.ini to database from progettoSNAPS.net
	# Bestgames (con, bgfile).addscores()


	#  User interface:

