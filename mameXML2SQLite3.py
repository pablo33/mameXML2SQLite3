#!/usr/bin/python3
# -*- encoding: utf-8 -*-

__version__ = "0.0"
__author__  = "pablo33"
__doc__		= """
	This software parses a MAME XML file into SQLite3 Database.
	Not all information are parsed.
	"""

# Standard libray imports
import os, argparse, sqlite3, re

# Functions
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


###### Defaults:
dbtest = True 


### Wich tags are retrieved from XML
# There are 2 tables: 
# 	one table for game information
#	one table for file rom information

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
		"isbios": 			("isbios"		,"char", ""),
		"isdevice":			("isdevice"		,"char", ""),
		"ismechanical":		("ismechanical"	,"char", ""),
		"runnable":			("runnable"		,"char", ""),
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


# main
if __name__ == '__main__':
	########################################
	# Retrieve cmd line parameters
	########################################
	parser = argparse.ArgumentParser()

	parser.add_argument("-x", "--xml", default="mame.xml",
						help="xml file path")

	args = parser.parse_args()

	# Retrieving variables from args
	xmlfile = args.xml

	# Checking parameters
	errorlist 	= []
	warninglist	= []
	if itemcheck(xmlfile) 	!= "file":
		errorlist.append ("I can't find the xml file:(--xml {})".format(xmlfile,))

	if len (warninglist) > 0:
		printlist (warninglist)
	if len (errorlist) > 0:
		errorlist.append ("Please revise errors and try again")
		printlist (errorlist)
		exit()

	########################################
	# Init Database
	########################################
	dbpath = os.path.splitext(xmlfile)[0] + ".sqlite3"

	if itemcheck (dbpath) == 'file':
		if not dbtest:
			print ("Database Found, loading it")
		else:
			os.remove (dbpath)
			print ("Generating a new SQLite database")

	con = sqlite3.connect (dbpath) # it creates one if file doesn't exists
	cursor = con.cursor() # object to manage queries

	tablefields = ",".join( [i[0]+" "+i[1]+" "+i[2] for i in gamefields_type.values()]) 
	cursor.execute (f'CREATE TABLE games ({tablefields})')

	tablefields = "name, " + ",".join( [i[0]+" "+i[1]+" "+i[2] for i in romsfields_type.values()]) 
	cursor.execute (f'CREATE TABLE roms ({tablefields})')

	tablefields = "name, " + ",".join( [i[0]+" "+i[1]+" "+i[2] for i in devsfields_type.values()]) 
	cursor.execute (f'CREATE TABLE devs ({tablefields})')

	con.commit()

class Readxmlline:
	def __t2dtags__ (self, txt):
		""" converts attributes string tag to dictionary
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
		tags = None
		text = None
		clos = False
		# Search for <tag attributes>
		res = re.search (r"<([a-z_]+) (.*)>",l)
		if res != None:
			tagg = res.group(1)
			tags = res.group(2)
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
		self.clos = clos
		self.tagg = tagg
		self.text = text
		self.tags = self.__t2dtags__(tags)
	def data (self):
		""" Returns read line data
			"""
		return (self.tagg, self.tags, self.text)

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
		yes_no = {"yes":True, "no":False}
		# for game data
		for i in gamefields_type:
			if gamefields_type[i][1] == 'int':
				self.gf[i] = int(self.gf[i])
			elif gamefields_type[i][1] == 'bool':
				self.gf[i] = yes_no[self.gf[i]]
		# for roms data
		newlist = []
		for j in self.rflist:
			newdict = j[1].copy()
			for i in romsfields_type:
				if romsfields_type[i][1] == 'int':
					newdict[i] = int(newdict[i])
				elif romsfields_type[i][1] == 'bool':
					newdict[i] = yes_no[newdict[i]]
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
					newdict[i] = yes_no[newdict[i]]
			newlist.append ((j[0],newdict))
		self.dflist = newlist.copy()

	def adddata (self,data):
		""" adds data for the game, data is a tuple from the XML extractor, (see Readxmlline class)
		(tagg, tags,text )
			"""
		# adding GameTable with attributes taggs
		if data[0] in gtTagg and data[1]!=None:
			# reading tags from input dict
			for i in gamefields:
				if i in data[1]:
					self.gf[i] = data[1].get(i)
		# adding GameTable Tag with text
		if data[0] in gtTxt:
			self.gf[data[0]]=data[2]
		# adding RomTable with attributes taggs
		if data[0] in rtTagg and data[1]!=None:
			# reading tags from input dict
			for i in romsfields:
				if i in data[1]:
					self.__rf__[i] = data[1].get(i)
			self.rflist.append ((self.gf['name'], self.__rf__.copy() ))
		# adding devTable with attributes taggs
		if data[0] in dtTagg and data[1]!=None:
			# reading tags from input dict
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
		con.commit()

fh = open(xmlfile)
stop = 1000000
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

	if gamecount >= stop:
		exit()


