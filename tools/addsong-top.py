#!/usr/bin/python
# -*- coding: utf-8 -*-
# MusicPlayer, https://github.com/albertz/music-player
# Copyright (c) 2013, Albert Zeyer, www.az2000.de
# All rights reserved.
# This code is under the 2-clause BSD license, see License.txt in the root directory of this project.

import sys, os

importPath = os.path.join(os.path.dirname(__file__), "..")
if importPath not in sys.path:
	sys.path += [importPath]

import better_exchook
if __name__ == "__main__":
	better_exchook.install()

from appinfo_args import argParser
argParser.parse_args = lambda: None

files = sys.argv[1:]
assert files, "usage: %s <files>" % sys.argv[0]
assert all([os.path.exists(fn) for fn in files]), "some files do not exist"

import shell
shell.connect()
shell.remoteExec("from Song import Song")
i = 0
for fn in files:
	assert os.path.exists(fn), "file %r does not exist" % fn
	shell.remoteExec("state.queue.queue.insert(%i, Song(%r))" % (i, fn))
	i += 1
