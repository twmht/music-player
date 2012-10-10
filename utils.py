# Import PyObjC here. This is because the first import of PyObjC *must* be
# in the main thread. Otherwise, the NSAutoreleasePool created automatically
# by PyObjC on the first import would be released at exit by the main thread
# which would crash (because it was created in a different thread).
# http://pyobjc.sourceforge.net/documentation/pyobjc-core/intro.html
try:
	import objc
except ImportError:
	# probably not MacOSX. doesn't matter
	pass

from collections import deque
from threading import Condition, Thread, currentThread
import sys

import better_exchook


class OnRequestQueue:
	class QueueEnd:
		def __init__(self):
			self.q = deque()
			self.cond = Condition()
			self.cancel = False
		def setCancel(self):
			with self.cond:
				self.cancel = True
				self.cond.notify()
	def __init__(self):
		self.queues = set()
	def put(self, item):
		for q in list(self.queues):
			with q.cond:
				if q.cancel: continue
				q.q.append(item)
				q.cond.notify()
	def cancelAll(self):
		for q in list(self.queues):
			q.setCancel()
	def read(self):
		q = self.QueueEnd()
		thread = currentThread()
		thread.waitQueue = q
		if thread.cancel:
			# This is to avoid a small race condition for the case
			# that the thread which wants to join+cancel us was faster
			# and didn't got the waitQueue. In that case, it would
			# have set the cancel already to True.
			return
		self.queues.add(q)
		while True:
			with q.cond:
				l = list(q.q)
				q.q.clear()
				cancel = q.cancel
				if not l and not cancel:
					q.cond.wait()
			for item in l:
				yield item
			if cancel: break
		self.queues.remove(q)

class EventCallback:
	def __init__(self, targetQueue, name=None):
		self.targetQueue = targetQueue
		self.name = name
	def __call__(self, *args, **kwargs):
		self.targetQueue.put((self, args, kwargs))
	def __repr__(self):
		return "<EventCallback %s>" % self.name

class initBy(object):
	def __init__(self, initFunc):
		self.initFunc = initFunc
		self.name = initFunc.func_name
	def load(self, inst):
		if not hasattr(self, "value"):
			self.value = self.initFunc(inst)
	def __get__(self, inst, type=None):
		if inst is None: # access through class
			return self
		self.load(inst)
		if hasattr(self.value, "__get__"):
			return self.value.__get__(inst, type)
		return self.value
	def __set__(self, inst, value):
		self.load(inst)
		if hasattr(self.value, "__set__"):
			return self.value.__set__(inst, value)
		self.value = value
		
class oneOf(object):
	def __init__(self, *consts):
		assert len(consts) > 0
		self.consts = consts
		self.value = consts[0]
	def __get__(self, inst, type=None):
		if inst is None: # access through class
			return self
		return self
	def __set__(self, inst, value):
		assert value in self.consts
		self.value = value

class UserAttrib(object):
	""" The idea/plan for this attrib type is:
	Use it in the GUI and display it nicely. Store every GUI related info here.
	I.e. this should say whether it is read-only to the user (if not visible to user at all ->
	 don't use this class), if it should be represented as a list, string, etc.
	 (this is the type, right now all Traits.TraitTypes), some other GUI decoration stuff,
	 etc.
	"""
	staticCounter = 0
	def __init__(self, name=None, type=None, writeable=False, updateHandler=None,
				 alignRight=False,
				 spaceX=None, spaceY=None,
				 variableWidth=False, variableHeight=False,
				 autosizeWidth=False,
				 highlight=False, lowlight=False,
				 canHaveFocus=False,
				 ):
		self.name = name
		self.type = type
		self.writeable = writeable
		self.updateHandler = updateHandler
		self.alignRight = alignRight
		self.spaceX = spaceX
		self.spaceY = spaceY
		self.variableWidth = variableWidth
		self.variableHeight = variableHeight
		self.autosizeWidth = autosizeWidth
		self.highlight = highlight
		self.lowlight = lowlight
		self.canHaveFocus = canHaveFocus
		self.__class__.staticCounter += 1
		# Keep an index. This is so that we know the order of initialization later on.
		# This is better for the GUI representation so we can order it the same way
		# as it is defined in the class.
		# iterUserAttribs() uses this.
		self.index = self.__class__.staticCounter
	def isType(self, T):
		try: return issubclass(self.type, T)
		except TypeError: return isinstance(self.type, T)
	@staticmethod
	def _getUserAttribDict(inst):
		if not hasattr(inst, "__userAttribs"):
			setattr(inst, "__userAttribs", {})
		return inst.__userAttribs
	@classmethod
	def _get(cls, name, inst):
		return cls._getUserAttribDict(inst)[name]
	def get(self, inst):
		try: return self._get(self.name, inst)
		except KeyError: return self.value
	def __get__(self, inst, type=None):
		if inst is None: # access through class
			return self
		if hasattr(self.value, "__get__"):
			return self.value.__get__(inst, type)
		return self.get(inst)
	@property
	def callDeco(self):
		class Wrapper:
			def __getattr__(_self, item):
				f = getattr(self.value, item)
				def wrappedFunc(arg): # a decorator expects a single arg
					value = f(arg)
					return self(value)
				return wrappedFunc
		return Wrapper()
	@classmethod
	def _set(cls, name, inst, value):
		cls._getUserAttribDict(inst)[name] = value
	def set(self, inst, value):
		self._set(self.name, inst, value)
	def __set__(self, inst, value):
		if inst is None: # access through class
			self.value = value
			return
		if hasattr(self.value, "__set__"):
			return self.value.__set__(inst, value)
		self.set(inst, value)
	@classmethod
	def _getName(cls, obj):
		if hasattr(obj, "name"): return obj.name
		elif hasattr(obj, "func_name"): return obj.func_name
		elif hasattr(obj, "fget"): return cls._getName(obj.fget)
		return None
	def __call__(self, attrib):
		if not self.name:
			self.name = self._getName(attrib)
		self.value = attrib
		return self
	def __repr__(self):
		return "<UserAttrib %s, %r>" % (self.name, self.type)

def iterUserAttribs(obj):
	attribs = []
	for attrib in dir(obj.__class__):
		attrib = getattr(obj.__class__, attrib)
		if attrib.__class__.__name__ == "UserAttrib":
			attribs += [attrib]
	attribs.sort(key = lambda attr: attr.index)
	return attribs

def formatTime(t):
	if t is None: return "?"
	mins = long(t // 60)
	t -= mins * 60
	hours = mins // 60
	mins -= hours * 60
	if hours: return "%02i:%02i:%02.0f" % (hours,mins,t)
	return "%02i:%02.0f" % (mins,t)

def formatFilesize(s):
	L = 800
	Symbols = ["byte", "KB", "MB", "GB", "TB"]
	i = 0
	while True:
		if s < L: break
		if i == len(Symbols) - 1: break
		s /= 1024.
		i += 1
	return "%.3g %s" % (s, Symbols[i])

def doAsync(f, name=None):
	from threading import Thread
	if name is None: name = repr(f)
	t = Thread(target = f, name = name)
	t.start()


def betterRepr(o):
	# the main difference: this one is deterministic
	# the orig dict.__repr__ has the order undefined.
	if isinstance(o, list):
		return "[\n" + "".join(map(lambda v: betterRepr(v) + ",\n", o)) + "]"
	if isinstance(o, deque):
		return "deque([\n" + "".join(map(lambda v: betterRepr(v) + ",\n", o)) + "])"
	if isinstance(o, tuple):
		return "(" + ", ".join(map(betterRepr, o)) + ")"
	if isinstance(o, dict):
		return "{\n" + "".join(map(lambda (k,v): betterRepr(k) + ": " + betterRepr(v) + ",\n", sorted(o.iteritems()))) + "}"
	# fallback
	return repr(o)

def takeN(iterator, n):
	i = 0
	l = [None] * n
	while i < n:
		try:
			l[i] = next(iterator)
		except StopIteration:
			l = l[0:i]
			break
		i += 1
	return l


def ObjectProxy(lazyLoader, custom_attribs={}, baseType=object):
	class Value: pass
	obj = Value()
	attribs = custom_attribs.copy()
	def load():
		if not hasattr(obj, "value"):
			obj.value = lazyLoader()
	def obj_getattribute(self, key):
		load()
		try: return getattr(obj.value, key)
		except AttributeError:
			return object.__getattribute__(self, key)				
	def obj_setattr(self, key, value):
		load()
		return setattr(obj.value, key, value)
	def obj_desc_get(self, inst, type=None):
		if inst is None:
			load()
			return obj.value
		return self
	def obj_desc_set(self, inst, value):
		if hasattr(value, "__get__"):
			# In case the value is itself some sort of ObjectProxy, try to get its
			# underlying object and use our proxy instead.
			obj.value = value.__get__(None)
		else:
			obj.value = value
	attribs.update({
		"__getattribute__": obj_getattribute,
		"__setattr__": obj_setattr,
		"__get__": obj_desc_get,
		"__set__": obj_desc_set,
		})
	# just set them so that we have them in the class. needed for __len__, __str__, etc.
	for a in dir(baseType):
		if a == "__new__": continue
		if a == "__init__": continue
		if a in attribs.keys(): continue
		class WrapProp(object):
			def __get__(self, inst, type=None, attrib=a):
				load()
				return object.__getattribute__(obj.value, attrib)
		attribs[a] = WrapProp()
	LazyObject = type("LazyObject", (object,), attribs)
	return LazyObject()

def PersistentObject(baseType, filename, persistentRepr = False, namespace = None):
	import appinfo
	fullfn = appinfo.userdir + "/" + filename
	def load():
		try:
			f = open(fullfn)
		except IOError: # e.g. file-not-found. that's ok
			return baseType()

		# some common types
		g = {baseType.__name__: baseType} # the baseType itself
		if namespace is None:
			g.update(globals()) # all what we have here
			if baseType.__module__:
				# the module of the basetype
				import sys
				m = sys.modules[baseType.__module__]
				g.update([(varname,getattr(m,varname)) for varname in dir(m)])
		else:
			g.update(namespace)
		obj = eval(f.read(), g)
		assert isinstance(obj, baseType)
		return obj
	def save(obj):
		s = betterRepr(obj.__get__(None))
		f = open(fullfn, "w")
		f.write(s)
		f.write("\n")
		f.close()
	def obj_repr(obj):
		if persistentRepr:
			return "PersistentObject(%s, %r)" % (baseType.__name__, filename)
		return betterRepr(obj.__get__(None))
	def obj_del(obj):
		save(obj)
	return ObjectProxy(load, baseType=baseType,
		custom_attribs={
			"save": save,
			"__repr__": obj_repr,
			"__del__": obj_del,
			})


class DictObj(dict):
	def __getattr__(self, item): return self[item]
	def __setattr__(self, key, value): self[key] = value


class Module:
	def __init__(self, name):
		self.name = name
		self.thread = None
		self.module = None
	@property
	def mainFuncName(self): return self.name + "Main"
	@property
	def moduleName(self): return self.name
	def start(self):
		self.thread = Thread(target = self.threadMain, name = self.name + " main")
		self.thread.waitQueue = None
		self.thread.cancel = False
		self.thread.reload = False
		self.thread.start()
	def threadMain(self):
		better_exchook.install()
		thread = currentThread()
		while True:
			if self.module:
				try:
					reload(self.module)
				except:
					print "couldn't reload module", self.module
					sys.excepthook(*sys.exc_info())
					# continue anyway, maybe it still works and maybe the mainFunc does sth good/important
			else:
				self.module = __import__(self.moduleName)
			mainFunc = getattr(self.module, self.mainFuncName)
			try:
				mainFunc()
			except SystemExit:
				raise
			except:
				print "Exception in thread", thread.name
				sys.excepthook(*sys.exc_info())
			if not thread.reload: break
			sys.stdout.write("reloading module %s\n" % self.name)
			thread.cancel = False
			thread.reload = False
			thread.waitQueue = None
	def stop(self, join=True):
		if not self.thread: return
		waitQueue = self.thread.waitQueue # save a ref in case the other thread already removes it
		self.thread.cancel = True
		if waitQueue: waitQueue.setCancel()
		if join:
			self.thread.join()
	def reload(self):
		if self.thread and self.thread.isAlive():
			self.thread.reload = True
			self.stop(join=False)
		else:
			self.start()
	def __str__(self):
		return "Module %s" % self.name



def objc_disposeClassPair(className):
	# Be careful using this!
	# Any objects holding refs to the old class will be invalid
	# and will probably crash!
	# Creating a new class after it will not make them valid because
	# the new class will be at a different address.

	# some discussion / example:
	# http://stackoverflow.com/questions/7361847/pyobjc-how-to-delete-existing-objective-c-class
	# https://github.com/albertz/chromehacking/blob/master/disposeClass.py

	import ctypes

	ctypes.pythonapi.objc_lookUpClass.restype = ctypes.c_void_p
	ctypes.pythonapi.objc_lookUpClass.argtypes = (ctypes.c_char_p,)

	addr = ctypes.pythonapi.objc_lookUpClass(className)
	if not addr: return False

	ctypes.pythonapi.objc_disposeClassPair.restype = None
	ctypes.pythonapi.objc_disposeClassPair.argtypes = (ctypes.c_void_p,)

	ctypes.pythonapi.objc_disposeClassPair(addr)


def objc_setClass(obj, clazz):
	objAddr = objc.pyobjc_id(obj) # returns the addr and also ensures that it is an objc object
	assert objAddr != 0

	import ctypes

	ctypes.pythonapi.objc_lookUpClass.restype = ctypes.c_void_p
	ctypes.pythonapi.objc_lookUpClass.argtypes = (ctypes.c_char_p,)

	className = clazz.__name__ # this should be correct I guess
	classAddr = ctypes.pythonapi.objc_lookUpClass(className)
	assert classAddr != 0

	# Class object_setClass(id object, Class cls)
	ctypes.pythonapi.object_setClass.restype = ctypes.c_void_p
	ctypes.pythonapi.object_setClass.argtypes = (ctypes.c_void_p,ctypes.c_void_p)

	ctypes.pythonapi.object_setClass(objAddr, classAddr)

	obj.__class__ = clazz

def do_in_mainthread(f, wait=True):
	from AppKit import NSThread
	if NSThread.isMainThread():
		return f()

	try:
		NSObject = objc.lookUpClass("NSObject")
		class PyAsyncCallHelper(NSObject):
			def initWithArgs_(self, f):
				self.f = f
				self.ret = None
				return self
			def call_(self, o):
				try:
					self.ret = self.f()
				except:
					print "Exception in PyAsyncCallHelper call"
					sys.excepthook(*sys.exc_info())					
	except:
		PyAsyncCallHelper = objc.lookUpClass("PyAsyncCallHelper") # already defined earlier

	helper = PyAsyncCallHelper.alloc().initWithArgs_(f)
	helper.performSelectorOnMainThread_withObject_waitUntilDone_(helper.call_, None, wait)
	return helper.ret

def ObjCClassAutorenamer(name, bases, dict):
	def lookUpClass(name):
		try: return objc.lookUpClass(name)
		except objc.nosuchclass_error: return None
	if lookUpClass(name):
		numPostfix = 1
		while lookUpClass("%s_%i" % (name, numPostfix)):
			numPostfix += 1
		name = "%s_%i" % (name, numPostfix)
	return type(name, bases, dict)



def getMusicPathsFromDirectory(dir):
	import os, appinfo
	matches = []
	for root, dirnames, filenames in os.walk(dir):
		for filename in filenames:
			if filename.endswith(tuple(appinfo.formats)):
				matches.append(os.path.join(root, filename))

	return matches


def getSongsFromDirectory(dir):
	songs = []
	files = getMusicPathsFromDirectory(dir)
	from Song import Song
	for file in files:
		songs.append(Song(file))

	return songs


# A fuzzy set is a dict of values to [0,1] numbers.

def unionFuzzySets(*fuzzySets):
	resultSet = {}
	for key in set.union(*map(set, fuzzySets)):
		value = max(map(lambda x: x.get(key, 0), fuzzySets))
		if value > 0:
			resultSet[key] = value
	return resultSet

def intersectFuzzySets(*fuzzySets):
	resultSet = {}
	for key in set.intersection(*map(set, fuzzySets)):
		value = min(map(lambda x: x[key], fuzzySets))
		if value > 0:
			resultSet[key] = value
	return resultSet

