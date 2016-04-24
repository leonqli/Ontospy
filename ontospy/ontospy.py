#!/usr/bin/env python
# encoding: utf-8
"""
ONTOSPY
Copyright (c) 2013-2016 __Michele Pasin__ <michelepasin.org>.
All rights reserved.

Run it from the command line by passing it an ontology URI,
or check out the help:

>>> python ontospy.py -h

More info in the README file.

"""


import sys, os, time, optparse, os.path, shutil, cPickle, urllib2, requests
from colorama import Fore, Style
from ConfigParser import SafeConfigParser

from ._version import *
from .core.graph import Graph
from .core.util import printDebug, pprint2columns, split_list


SHELL_EXAMPLES = """
Quick Examples:
  > ontospy http://xmlns.com/foaf/spec/    # ==> prints info about FOAF
  > ontospy http://xmlns.com/foaf/spec/ -i # ==> prints info and save local copy
  > ontospy http://xmlns.com/foaf/spec/ -g # ==> exports ontology data into a github gist 
  
  For more, visit ontospy.readthedocs.org

"""



# ===========
# STATIC VARIABLES AND PATHS
# ===========


# python package installation
_dirname, _filename = os.path.split(os.path.abspath(__file__))
ONTOSPY_SOUNDS = _dirname + "/data/sounds/"
ONTOSPY_LOCAL_TEMPLATES = _dirname + "/data/templates/"


# local repository constants
ONTOSPY_LOCAL = os.path.join(os.path.expanduser('~'), '.ontospy')
ONTOSPY_LOCAL_VIZ = ONTOSPY_LOCAL + "/viz"
ONTOSPY_LOCAL_CACHE = ONTOSPY_LOCAL + "/.cache/" + VERSION + "/"

ONTOSPY_LIBRARY_DEFAULT = ONTOSPY_LOCAL + "/models/"
# ONTOSPY_LIBRARY_DEFAULT = 
# os.path.join(os.path.expanduser('~'), 'ontospy-library')


BOOTSTRAP_ONTOLOGIES = [
	"http://xmlns.com/foaf/spec/" ,
	# "https://www.w3.org/2006/time" ,
	"http://www.w3.org/TR/2003/PR-owl-guide-20031209/wine" ,
	"http://purl.uniprot.org/core/" ,
	"http://purl.org/spar/cito/" ,
	"http://ns.nature.com/terms/" ,

	"http://www.ontologydesignpatterns.org/ont/dul/DUL.owl",
	"http://www.ifomis.org/bfo/1.1",
	"http://topbraid.org/schema/schema.ttl",
	"http://www.cidoc-crm.org/rdfs/cidoc_crm_v6.0-draft-2015January.rdfs",
]



# ===========
# GLOBAL METHODS AND UTILS
# ===========



def get_or_create_home_repo(reset=False):
	"""
	Check to make sure we never operate with a non-existing local repo 
	"""
	dosetup = True
	if os.path.exists(ONTOSPY_LOCAL):
		dosetup = False

		if reset:
			var = raw_input("Delete the local library and all of its contents? (y/n) ")
			if var == "y":
				shutil.rmtree(ONTOSPY_LOCAL)
				dosetup = True
			else:
				var == "n"

	if dosetup or not(os.path.exists(ONTOSPY_LOCAL)):
		os.mkdir(ONTOSPY_LOCAL)
	if dosetup or not(os.path.exists(ONTOSPY_LOCAL_CACHE)): 
		os.mkdir(ONTOSPY_LOCAL_CACHE)
	if dosetup or not(os.path.exists(ONTOSPY_LOCAL_VIZ)):	
		os.mkdir(ONTOSPY_LOCAL_VIZ) 
	if dosetup or not(os.path.exists(ONTOSPY_LIBRARY_DEFAULT)): 
		os.mkdir(ONTOSPY_LIBRARY_DEFAULT)

	LIBRARY_HOME = get_home_location()  # from init file, or default

	# check that the local library folder exists, otherwiese prompt user to create it
	if not(os.path.exists(LIBRARY_HOME)):
		printDebug("Warning: the local library at '%s' has been deleted or is not accessible anymore." % LIBRARY_HOME, "important")
		printDebug("Please reset the local library by running 'ontospy-utils -u <a-valid-path>'", "comment")
		raise SystemExit, 1

	if dosetup:		
		print Fore.GREEN + "Setup successfull: local library created at <%s>" % LIBRARY_HOME + Style.RESET_ALL
	else:
		print Style.DIM + "Local library: <%s>" % LIBRARY_HOME + Style.RESET_ALL

	return True 






def get_home_location():
	"""Gets the path of the folder for the local library - returns a string"""
	config = SafeConfigParser()
	config_filename = ONTOSPY_LOCAL + '/config.ini'
	config.read(config_filename)
	try:
		return config.get('models', 'dir')
	except:
		# FIRST TIME, create it
		config.add_section('models')
		config.set('models', 'dir', ONTOSPY_LIBRARY_DEFAULT)
		with open(config_filename, 'w') as f:
			# note: this does not remove previously saved settings 
			config.write(f)

		return ONTOSPY_LIBRARY_DEFAULT



def get_localontologies():
	"returns a list of file names in the ontologies folder (not the full path)"
	res = []
	ONTOSPY_LOCAL_MODELS = get_home_location()
	if os.path.exists(ONTOSPY_LOCAL_MODELS):
		for f in os.listdir(ONTOSPY_LOCAL_MODELS):
			if os.path.isfile(os.path.join(ONTOSPY_LOCAL_MODELS, f)):
				if not f.startswith(".") and not f.endswith(".pickle"):
					res += [f]
	else:
		print "No local library found. Use the --reset command"					
	return res


def get_pickled_ontology(filename):
	""" try to retrieve a cached ontology """
	pickledfile = ONTOSPY_LOCAL_CACHE + "/" + filename + ".pickle"
	if os.path.isfile(pickledfile):
		try:
			return cPickle.load(open(pickledfile, "rb"))
		except:
			print Style.DIM + "** WARNING: Cache is out of date ** ...recreating it... " + Style.RESET_ALL
			return None
	else:
		return None


def del_pickled_ontology(filename):
	""" try to remove a cached ontology """
	pickledfile = ONTOSPY_LOCAL_CACHE + "/" + filename + ".pickle"
	if os.path.isfile(pickledfile):
		os.remove(pickledfile)
		return True
	else:
		return None


def rename_pickled_ontology(filename, newname):
	""" try to rename a cached ontology """
	pickledfile = ONTOSPY_LOCAL_CACHE + "/" + filename + ".pickle"
	newpickledfile = ONTOSPY_LOCAL_CACHE + "/" + newname + ".pickle"
	if os.path.isfile(pickledfile):
		os.rename(pickledfile, newpickledfile)
		return True
	else:
		return None


def do_pickle_ontology(filename, g=None):
	""" 
	from a valid filename, generate the graph instance and pickle it too
	note: option to pass a pre-generated graph instance too	 
	2015-09-17: added code to increase recursion limit if cPickle fails
		see http://stackoverflow.com/questions/2134706/hitting-maximum-recursion-depth-using-pythons-pickle-cpickle
	"""
	ONTOSPY_LOCAL_MODELS = get_home_location()
	pickledpath = ONTOSPY_LOCAL_CACHE + "/" + filename + ".pickle"
	if not g:
		g = Graph(ONTOSPY_LOCAL_MODELS + "/" + filename)	
	
	try:				
		cPickle.dump(g, open(pickledpath, "wb"))
		# print Style.DIM + ".. cached <%s>" % pickledpath + Style.RESET_ALL
	except Exception, e: 
		print Style.DIM + "\n.. Failed caching <%s>" % filename + Style.RESET_ALL
		print str(e)
		print Style.DIM + "\n... attempting to increase the recursion limit from %d to %d" % (sys.getrecursionlimit(), sys.getrecursionlimit()*10) + Style.RESET_ALL

		try:
			sys.setrecursionlimit(sys.getrecursionlimit()*10)
			cPickle.dump(g, open(pickledpath, "wb"))
			print Style.BRIGHT + "... SUCCESSFULLY cached <%s>" % pickledpath + Style.RESET_ALL
		except Exception, e: 
			print Style.BRIGHT + "\n... Failed caching <%s>... aborting..." % filename + Style.RESET_ALL
			print str(e)	
		sys.setrecursionlimit(sys.getrecursionlimit()/10)
	return g



def actionSelectFromLocal():
	" select a file from the local repo "
	
	options = get_localontologies()
	
	counter = 1
	printDebug("------------------", 'comment')
	if not options:
		printDebug("Your local library is empty. Use 'ontospy -i <uri>' to add more ontologies to it.")
	else:
		data = []
		for x in options:
			data += [ Fore.BLUE + Style.BRIGHT + "[%d] " % counter + Style.RESET_ALL + x + Style.RESET_ALL]
			counter += 1
		
		# from util.
		pprint2columns(data)
	
		while True:
			printDebug("------------------\nSelect a model by typing its number: (q=quit)", "important")
			var = raw_input()
			if var == "q":
				return None
			else:
				try:
					_id = int(var)
					ontouri = options[_id - 1]
					printDebug("You selected:", "comment")
					printDebug("---------\n" + ontouri + "\n---------", "red")
					return ontouri
				except:
					printDebug("Please enter a valid number.", "comment")
					continue



def action_import(location, verbose=True, lock=None):
	"""import files into the local repo """

	location = str(location) # prevent errors from unicode being passed

	# 1) extract file from location and save locally
	ONTOSPY_LOCAL_MODELS = get_home_location()
	fullpath = ""
	try:
		if location.startswith("www."): #support for lazy people
			location = "http://%s" % str(location)
		if location.startswith("http://"):
			# print "here"
			headers = {'Accept': "application/rdf+xml"}
			req = urllib2.Request(location, headers=headers)
			res = urllib2.urlopen(req)
			final_location = res.geturl()  # after 303 redirects
			printDebug("Saving data from <%s>" % final_location, "green")
			# filename = final_location.split("/")[-1] or final_location.split("/")[-2]
			filename = location.replace("http://", "").replace("/", "_")
			if not filename.lower().endswith(('.rdf', '.owl', '.rdfs', '.ttl', '.n3')):
				filename = filename + ".rdf"
			fullpath = ONTOSPY_LOCAL_MODELS + "/" + filename # 2016-04-08
			# fullpath = ONTOSPY_LOCAL_MODELS + filename

			# print "==DEBUG", final_location, "**", filename,"**", fullpath
			
			file_ = open(fullpath, 'w')
			file_.write(res.read())
			file_.close()
		else:
			if os.path.isfile(location):
				filename = location.split("/")[-1] or location.split("/")[-2]
				fullpath = ONTOSPY_LOCAL_MODELS + "/" + filename
				shutil.copy(location, fullpath)
			else:
				raise ValueError('The location specified is not a file.')
		# print "Saved local copy"
	except:
		printDebug("Error retrieving file. Please make sure <%s> is a valid location." % location, "important")
		if os.path.exists(fullpath):
			os.remove(fullpath)
		return None

	if False: # for testing threading
			# April 17, 2016: this works, but we gain NOTHING IN TIME!!! 
			# maybe a better strategy if to thread the Graph instantation
		if lock:
			lock.acquire()
		try:
			g = Graph(fullpath, verbose=verbose)
		finally:
			if lock:
				lock.release()
	if True:
	# 2) check if valid RDF and cache it
		try:
			g = Graph(fullpath, verbose=verbose)
			printDebug("----------")
		except:
			g = None
			if os.path.exists(fullpath):
				os.remove(fullpath)
			printDebug("Error parsing file. Please make sure %s contains valid RDF." % location, "important")

	if g:
		printDebug("Caching...", "red")
		do_pickle_ontology(filename, g)
		printDebug("----------\n...completed!", "important")

	# finally...
	return g



def action_import_folder(location):
	"""Try to import all files from a local folder"""

	if os.path.isdir(location):
		onlyfiles = [ f for f in os.listdir(location) if os.path.isfile(os.path.join(location,f)) ]
		for file in onlyfiles:
			if not file.startswith("."):
				filepath = os.path.join(location,file)
				print Fore.RED + "\n---------\n" + filepath + "\n---------" + Style.RESET_ALL
				return action_import(filepath)
	else:
		printDebug("Not a valid directory", "important")
		return None


# ==============
# BOOTSTRAP WITH THREADS TEST

import threading
import Queue

class ThreadUrl(threading.Thread):
	"""Threaded Url Grab"""
	def __init__(self, queue, lock):
		threading.Thread.__init__(self)
		self.queue = queue
		self.lock = lock
  
	def run(self):
		while True:
			#grabs host from queue
			host = self.queue.get()
			# self.lock.acquire()
			#grabs urls
			action_import(host, verbose=False, lock=self.lock)
			# finally:
			# 	self.lock.release()

			#signals to queue job is done
			self.queue.task_done()


def SECONDATTEMPT_action_bootstrap_threads():
	"""Bootstrap the local REPO with a few cool ontologies

	# here I tried using the patter found at
	http://www.ibm.com/developerworks/aix/library/au-threadingpython/
	"""
 
	# list ontologies
	printDebug("--------------")
	printDebug("The following ontologies will be imported:")
	printDebug("--------------")	
	count = 0 
	for s in BOOTSTRAP_ONTOLOGIES:
		count += 1
		print count, "<%s>" % s

	printDebug("--------------")
	printDebug("Note: this operation may take several minutes.")
	printDebug("Are you sure? [Y/N]")
	# var = raw_input()
	var = "Y" # for testing

	queue = Queue.Queue()
	lock = threading.Lock()

	#spawn a pool of threads, and pass them queue instance 
	for i in range(5):
		t = ThreadUrl(queue, lock)
		# t.setDaemon(True)
		t.start()

	#populate queue with data   
	for host in BOOTSTRAP_ONTOLOGIES[:1]:
		queue.put(host)
		   
	#wait on the queue until everything has been processed     
	queue.join()

	return True




def worker1(uri, lock):
	"""thread worker function"""
	print threading.currentThread().getName(), 'Starting {{{{{{{{{{{'
	printDebug("--------------")
	action_import(uri, verbose=False, lock=lock)
	# try:
	# 	printDebug("--------------")
	# 	action_import(uri, verbose=False)
	# except:
	# 	printDebug("OPS... An Unknown Error Occurred - Aborting Installation of %s" % uri)
	print threading.currentThread().getName(), 'Exiting >>>>>>>>>>>>>'
	return


def worker2(uri_list, lock):
	"""thread worker function"""
	print threading.currentThread().getName(), 'Starting {{{{{{{{{{{'
	printDebug("--------------")
	for uri in uri_list:
		action_import(uri, verbose=False, lock=lock)
	print threading.currentThread().getName(), 'Exiting >>>>>>>>>>>>>'	
	return

				
def action_bootstrap_threads():
	"""Bootstrap the local REPO with a few cool ontologies"""

 
	# list ontologies
	printDebug("--------------")
	printDebug("The following ontologies will be imported:")
	printDebug("--------------")	
	count = 0 
	for s in BOOTSTRAP_ONTOLOGIES:
		count += 1
		print count, "<%s>" % s

	printDebug("--------------")
	printDebug("Note: this operation may take several minutes.")
	printDebug("Are you sure? [Y/N]")
	# var = raw_input()
	var = "Y" # for testing

	threads = []

	lock = threading.Lock()

	# do import using threads
	if var == "y" or var == "Y":

		if True:
			for uri in BOOTSTRAP_ONTOLOGIES:
				t = threading.Thread(target=worker1, args=(uri,lock))
				threads.append(t)
				t.start()
			return True	
		else:
			for group in split_list(BOOTSTRAP_ONTOLOGIES[:8], wanted_parts=4):
				t = threading.Thread(target=worker2, args=(group,lock))
				threads.append(t)
				t.start()
			return True	
	else:
		printDebug("--------------")
		printDebug("Goodbye")
		return False 


# ==============
# END OF TESTS WITH THREADS  ===ends
# ==============






def action_bootstrap():
	"""Bootstrap the local REPO with a few cool ontologies"""
	printDebug("--------------")
	printDebug("The following ontologies will be imported:")
	printDebug("--------------")
	count = 0 
	for s in BOOTSTRAP_ONTOLOGIES:
		count += 1
		print count, "<%s>" % s

	printDebug("--------------")
	printDebug("Note: this operation may take several minutes.")
	printDebug("Are you sure? [Y/N]")
	var = raw_input()
	if var == "y" or var == "Y":
		for uri in BOOTSTRAP_ONTOLOGIES:
			try:
				printDebug("--------------")
				action_import(uri, verbose=False)
			except:
				printDebug("OPS... An Unknown Error Occurred - Aborting Installation")
		return True	
	else:
		printDebug("--------------")
		printDebug("Goodbye")
		return False 


	




def action_webimport_select():
	""" select from the available online directories for import """
	DIR_OPTIONS = {1 : "http://lov.okfn.org", 2 : "http://prefix.cc/popular/"}
	selection = None
	while True:
		printDebug("----------")
		text = "Please select which online directory to scan: (q=quit)\n"
		for x in DIR_OPTIONS:
			text += "%d) %s\n" % (x, DIR_OPTIONS[x])
		var = raw_input(text + ">")
		if var == "q":
			return None
		else:
			try:
				selection = int(var)
				test = DIR_OPTIONS[selection]  #throw exception if number wrong
				break
			except:
				printDebug("Invalid selection. Please try again.", "important")
				continue


	try:
		if selection == 1:
			action_webimport_LOV()
		elif selection == 2:
			action_webimport_PREFIXCC()
	except:
		printDebug("Sorry, the online repository seems to be unreachable.")

	return True



def action_webimport_LOV(baseuri="http://lov.okfn.org/dataset/lov/api/v2/vocabulary/list"):
	"""
	2016-03-02: import from json list 
	"""

	printDebug("----------\nReading source... <%s>" % baseuri)
	query = requests.get(baseuri, params={})
	options = query.json()
	printDebug("----------\n%d results found." % len(options))

	counter = 1
	for x in options:
		uri, title, ns = x['uri'], x['titles'][0]['value'], x['nsp']
# print "%s ==> %s" % (d['titles'][0]['value'], d['uri'])

		print Fore.BLUE + Style.BRIGHT + "[%d]" % counter, Style.RESET_ALL + uri + " ==> ", Fore.RED + title, Style.RESET_ALL

		counter += 1

	while True:
		var = raw_input(Style.BRIGHT + "=====\nSelect ID to import: (q=quit)\n" + Style.RESET_ALL)
		if var == "q":
			break
		else:
			try:
				_id = int(var)
				ontouri = options[_id - 1]['uri']
				print Fore.RED + "\n---------\n" + ontouri + "\n---------" + Style.RESET_ALL
				action_import(ontouri)
			except:
				print "Error retrieving file. Import failed."
				continue


		# from extras.web import getCatalog
		# # _list = getCatalog(query=opts.query) # 2015-11-01: no query for now
		# _list = getCatalog(query="")
		# action_webimport(_list)	




def action_webimport_PREFIXCC():
	"""
	List models from web catalog (prefix.cc) and ask which one to import
	2015-10-10: originally part of main ontospy; now standalone only 
	"""

	from extras.web import getCatalog
	options = getCatalog(query="")

	counter = 1
	for x in options:
		print Fore.BLUE + Style.BRIGHT + "[%d]" % counter, Style.RESET_ALL + x[0] + " ==> ", Fore.RED +	 x[1], Style.RESET_ALL
		# print Fore.BLUE + x[0], " ==> ", x[1]
		counter += 1

	while True:
		var = raw_input(Style.BRIGHT + "=====\nSelect ID to import: (q=quit)\n" + Style.RESET_ALL)
		if var == "q":
			break
		else:
			try:
				_id = int(var)
				ontouri = options[_id - 1][1]
				print Fore.RED + "\n---------\n" + ontouri + "\n---------" + Style.RESET_ALL
				action_import(ontouri)
			except:
				print "Error retrieving file. Import failed."
				continue





def action_export(args, save_gist, fromshell=False):
	"""
	export model into another format eg html, d3 etc...
	<fromshell> : the local name is being passed from ontospy shell
	"""
	
	from extras import exporter  
					
	# select from local ontologies:
	if not(args):
		ontouri = actionSelectFromLocal()
		if ontouri:	
			islocal = True		
		else:	
			raise SystemExit, 1
	elif fromshell:
		ontouri = args
		islocal = True
	else:
		ontouri = args[0]
		islocal = False

	
	# select a visualization
	viztype = exporter._askVisualization()
	if not viztype:
		return None
		# raise SystemExit, 1
	
	
	# get ontospy graph
	if islocal:
		g = get_pickled_ontology(ontouri)
		if not g:
			g = do_pickle_ontology(ontouri)	
	else:
		g = Graph(ontouri)
	
	

	# viz DISPATCHER
	if viztype == 1:
		contents = exporter.htmlBasicTemplate(g, save_gist)

	elif viztype == 2:
		contents = exporter.interactiveD3Tree(g, save_gist)	
				

	# once viz contents are generated, save file locally or on github
	if save_gist:
		urls = exporter.saveVizGithub(contents, ontouri)
		printDebug("...documentation saved on GitHub!", "comment")
		printDebug("Gist: " + urls['gist'], "important")
		printDebug("Blocks Gist: " + urls['blocks'], "important")
		printDebug("Full Screen Blocks Gist: " + urls['blocks_fullwin'], "important")
		url = urls['blocks'] # defaults to full win
	else:
		url = exporter.saveVizLocally(contents)
		printDebug("...documentation generated! [%s]" % url, "comment")

	return url






##################
# 
#  COMMAND LINE 
#
##################




def shellPrintOverview(g, opts):
	ontologies = g.ontologies
				
	for o in ontologies:
		print Style.BRIGHT + "\nOntology Annotations\n-----------" + Style.RESET_ALL
		o.printTriples()
	if g.classes:
		print Style.BRIGHT + "\nClass Taxonomy\n" + "-" * 10  + Style.RESET_ALL
		g.printClassTree(showids=False, labels=opts['labels'])
	if g.properties:
		print Style.BRIGHT + "\nProperty Taxonomy\n" + "-" * 10	 + Style.RESET_ALL
		g.printPropertyTree(showids=False, labels=opts['labels'])
	if g.skosConcepts:
		print Style.BRIGHT + "\nSKOS Taxonomy\n" + "-" * 10	 + Style.RESET_ALL
		g.printSkosTree(showids=False, labels=opts['labels'])
			





def parse_options():
	"""
	parse_options() -> opts, args

	Parse any command-line options given returning both
	the parsed options and arguments.
	
	https://docs.python.org/2/library/optparse.html
	
	note: invoke help with `parser.print_help()`
	
	"""

	class MyParser(optparse.OptionParser):
		def format_epilog(self, formatter):
			return self.epilog

	parser = MyParser(usage=USAGE, version=VERSION, epilog=SHELL_EXAMPLES)	
	# parser = optparse.OptionParser(usage=USAGE, version=VERSION)
				
	parser.add_option("-l", "",
			action="store_true", default=False, dest="_library",
			help="LIBRARY: select ontologies saved in the local library") 

	parser.add_option("-v", "",
			action="store_true", default=False, dest="labels",
			help="VERBOSE: show entities labels as well as URIs")

	parser.add_option("-b", "",
			action="store_true", default=False, dest="_bootstrap",
			help="BOOTSTRAP: save some sample ontologies into the local library")

	parser.add_option("-i", "",
			action="store_true", default=False, dest="_import",
			help="IMPORT: save a file/folder/url into the local library")

	parser.add_option("-w", "",
			action="store_true", default=False, dest="_web",
			help="IMPORT-FROM-REPO: import from an online directory")

	parser.add_option("-e", "",
			action="store_true", default=False, dest="_export",
			help="EXPORT: export a model into another format (e.g. html)")
	
	parser.add_option("-g", "",
			action="store_true", default=False, dest="_gist",
			help="EXPORT-AS-GIST: export output as a Github Gist.")
								
	
	opts, args = parser.parse_args()
					
	return opts, args, parser






	
def main():
	""" command line script """
	
	printDebug("OntoSPy " + VERSION, "comment")
	opts, args, parser = parse_options()
	sTime = time.time()

	get_or_create_home_repo()
	
	print_opts = {
					'labels' : opts.labels,
				}


	# default behaviour: launch shell
	if not args and not opts._library and not opts._import and not opts._web and not opts._export and not opts._gist and not opts._bootstrap:	
		from shell import Shell, STARTUP_MESSAGE
		Shell()._clear_screen()
		print STARTUP_MESSAGE
		Shell().cmdloop()
		raise SystemExit, 1
		

	# select a model from the local ontologies
	elif opts._export or opts._gist:		
		# if opts._gist and not opts._export:
		# 	printDebug("WARNING: the -g option must be used in combination with -e (=export)")
		# 	sys.exit(0)
		import webbrowser
		url = action_export(args, opts._gist)
		if url:# open browser	
			webbrowser.open(url)

		# continue and print timing at bottom 
		


	# select a model from the local ontologies (assuming it's not opts._export)
	elif opts._library:
		filename = actionSelectFromLocal()
		if filename:
			g = get_pickled_ontology(filename)
			if not g:
				g = do_pickle_ontology(filename)	
			shellPrintOverview(g, print_opts)		
			# printDebug("----------\n" + "Completed", "comment")
		# continue and print timing at bottom 


	# bootstrap local repo
	elif opts._bootstrap:
		THREADS = False
		if THREADS:
			action_bootstrap_threads()
			raise SystemExit, 1
		else:
			action_bootstrap()
			printDebug("----------\n" + "Completed (note: load a local model by typing `ontospy -l`)", "comment")
			
	# import an ontology (ps implemented in both .ontospy and .extras)
	elif opts._import:
		if not args:
			printDebug("WARNING: please specify a file/folder/url to import into local library.")
			sys.exit(0)		
		_location = args[0]
		if os.path.isdir(_location):
			res = action_import_folder(_location)
		else:
			res = action_import(_location)
		if res: 
			printDebug("----------\n" + "Completed (note: load a local model by typing `ontospy -l`)", "comment") 
		# continue and print timing at bottom


			
	elif opts._web:
		action_webimport_select()
		raise SystemExit, 1
		
		

		
	# last case: a new URI/path is passed
	# load the ontology when a uri is passed manually
	elif args:
		printDebug("----------\nYou passed the argument: <%s>" % str(args[0]), "comment")
		g = Graph(args[0])	
		shellPrintOverview(g, print_opts)

	# finally: print some stats.... 
	eTime = time.time()
	tTime = eTime - sTime
	printDebug("\n----------\n" + "Time:	   %0.2fs" %  tTime, "comment")



	
if __name__ == '__main__':
	import sys
	try:
		main()
		sys.exit(0)
	except KeyboardInterrupt, e: # Ctrl-C
		raise e



	

