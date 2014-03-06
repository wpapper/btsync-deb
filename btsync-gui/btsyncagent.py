# coding=utf-8
#
# Copyright 2014 Leo Moll
#
# Authors: Leo Moll and Contributors (see CREDITS)
#
# Thanks to Mark Johnson for btsyncindicator.py which gave me the
# last nudge needed to learn python and write my first linux gui
# application. Thank you!
#
# This file is part of btsync-gui. btsync-gui is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>
#

import os
import json
import time
import stat
import signal
import logging
import argparse
import subprocess

from btsyncutils import BtSingleton, BtSingleInstanceException

class BtSyncAgentException(Exception):
	def __init__(self,retcode,message):
		self.retcode = retcode
		self.message = message
	def __str__(self):
		return repr(self.message)
	def __int__(self):
		return repr(self.retcode)

class BtSyncAgent:
	# still hardcoded - this is the binary location of btsync when installing
	# the package btsync-common
	BINARY = '/usr/lib/btsync-common/btsync-core'
	# BEWARE: the following API key is owned by tuxpoldo! If you write your own
	#         application, do NOT take this, but request your own key by folling
	#         out the form at http://www.bittorrent.com/sync/developers
	APIKEY = '26U2OU3LNXN4I3QFNT7JAGG5DB676PCZIEL42FBOGYUM4OUMI5YTBNLD64ZXJCLSFWKC'\
		'VOFNPU65UVO5RKSMYJ24A2KX3VPS4S7HICM3U7OI3FUHMXJPSLMBV4XNRKEMNOBDK4I'

	def __init__(self,args):
		self.args = args
		self.uid = int(os.getuid())
		self.pid = None
		self.configpath = os.environ['HOME'] + '/.config/btsync'
		self.storagepath = os.environ['HOME'] + '/.btsync'
		self.pidfile = self.configpath + '/btsync-agent.pid'
		self.conffile = self.configpath + '/btsync-agent.conf'
		self.preffile = self.configpath + '/btsync-gui.prefs'
		self.lockfile = self.configpath + '/btsync-gui.pid'
		self.lock = None
		self.prefs = {}
		# load values from preferences
		self.load_prefs()
		# TODO: the automatically started btsync engine, should get randomly
		#       created credentials at each start. See Issue #67
		self.username = self.get_pref('username','btsync-gui')
		self.password = self.get_pref('password','P455w0rD')
		self.bindui = self.get_pref('bindui','127.0.0.1')
		self.portui = self.get_pref('portui',self.uid + 8999)
		# process command line arguments
		if self.args.username is not None:
			self.username = self.args.username
		if self.args.password is not None:
			self.password = self.args.password
		if self.args.bindui is not None:
			self.bindui = '0.0.0.0' if self.args.bindui == 'auto' else self.args.bindui
		if self.args.port != 0:
			self.portui = self.args.port
		if self.args.cleardefaults:
			# clear saved defaults
			if 'username' in self.prefs:
				del self.prefs['username']
			if 'password' in self.prefs:
				del self.prefs['password']
			if 'bindui' in self.prefs:
				del self.prefs['bindui']
			if 'portui' in self.prefs:
				del self.prefs['portui']
			self.save_prefs()
			raise BtSyncAgentException(0, 'Default settings cleared.')
		if self.args.savedefaults:
			# save new defaults
			if self.args.username is None:
				raise BtSyncAgentException(-1,
					'Username must be specified when saving defaults')
			if self.args.password is None:
				raise BtSyncAgentException(-1,
					'Username must be specified when saving defaults')
			self.set_pref('username',self.username)
			self.set_pref('password',self.password)
			if self.args.bindui is not None:
				# changed bind address for web ui
				self.set_pref('bindui',self.bindui)
			if self.args.port != 0:
				# changed bind port for web ui
				self.set_pref('portui',self.portui)
			raise BtSyncAgentException(0, 'Default settings saved.')

		if self.is_auto():
			self.lock = BtSingleton(self.lockfile,'btsync-gui')

	def __del__(self):
		self.shutdown()

	def startup(self):
		if self.args.host == 'auto':
			# we have to handle everything
			try:
				if not os.path.isdir(self.configpath):
					os.makedirs(self.configpath)
				if not os.path.isdir(self.storagepath):
					os.makedirs(self.storagepath)

				while self.is_running():
					logging.info ('Found running btsync agent. Stopping...')
					os.kill (self.pid, signal.SIGTERM)
					time.sleep(1)
					
				self.make_config_file()
				if not self.is_running():
					logging.info ('Starting btsync agent...')
					subprocess.call([BtSyncAgent.BINARY, '--config', self.conffile])
					time.sleep(0.5)
					if self.is_running():
						# no guarantee that it's already running...
						self.kill_config_file()
			except Exception:
				logging.critical('Failure to start btsync agent - exiting...')
				exit (-1)

	def suspend(self):
		if self.args.host == 'auto':
			pass

	def resume(self):
		if self.args.host == 'auto':
			pass

	def shutdown(self):
		if self.is_primary() and self.is_running():
			logging.info ('Stopping btsync agent...')
			os.kill (self.pid, signal.SIGTERM)
			self.kill_config_file()

	def set_pref(self,key,value,flush=True):
		self.prefs[key] = value
		if flush:
			self.save_prefs()

	def get_pref(self,key,default):
		return self.prefs.get(key,default)

	def load_prefs(self):
		try:
			pref = open (self.preffile, 'r')
			result = json.load(pref)
			pref.close()
			if isinstance(result,dict):
				self.prefs = result
			else:
				print "Error: " +str(result)
		except Exception as e:
			logging.warning('Error while loading preferences: {0}'.format(e))
			self.prefs = {}
			pass

	def save_prefs(self):
		try:
			pref = open (self.preffile, 'w')
			os.chmod(self.preffile, stat.S_IRUSR | stat.S_IWUSR)
			json.dump(self.prefs,pref)
			pref.close()
		except Exception as e:
			logging.error('Error while saving preferences: {0}'.format(e))
			pass

	def is_auto(self):
		return self.args.host == 'auto'

	def is_primary(self):
		return self.args.host == 'auto' and isinstance(self.lock,BtSingleton)

	def get_lock_filename(self):
		return os.environ['HOME'] + '/.config/btsync/btsync-gui.lock'

	def get_host(self):
		return 'localhost' if self.is_auto() else self.args.host

	def get_port(self):
		return self.portui if self.is_auto() else self.args.port

	def get_username(self):
		return self.username if self.is_auto() else self.args.username

	def get_password(self):
		return self.password if self.is_auto() else self.args.password

	def get_debug(self):
		if self.args.host == 'auto':
			return os.path.isfile(self.storagepath + '/debug.txt')
		else:
			return False

	def set_debug(self,activate=True):
		if self.args.host == 'auto':
			if activate:
				deb = open (self.storagepath + '/debug.txt', 'w')
				deb.write('FFFF\n')
				deb.close
			else:
				os.remove (self.storagepath + '/debug.txt')

	def make_config_file(self):
		try:
			cfg = open (self.conffile, 'w')
			os.chmod(self.conffile, stat.S_IRUSR | stat.S_IWUSR)
			cfg.write('{\n')
			cfg.write('\t"pid_file" : "{0}",\n'.format(self.pidfile))
			cfg.write('\t"storage_path" : "{0}",\n'.format(self.storagepath))
			# cfg.write('\t"use_gui" : false,\n')
			cfg.write('\t"webui" : \n\t{\n')
			cfg.write('\t\t"listen" : "{0}:{1}",\n'.format(self.bindui,self.portui))
			cfg.write('\t\t"login" : "{0}",\n'.format(self.username))
			cfg.write('\t\t"password" : "{0}",\n'.format(self.password))
			cfg.write('\t\t"api_key" : "{}"\n'.format(BtSyncAgent.APIKEY))
			cfg.write('\t}\n')
			cfg.write('}\n')
			cfg.close()
		except Exception:
			logging.critical('Cannot create {0} - exiting...'.format(self.configpath))
			exit (-1)

	def kill_config_file(self):
		if os.path.isfile(self.conffile+'a'):
			os.remove(self.conffile)

	def read_pid(self):
		try:
			pid = open (self.pidfile, 'r')
			pidstr = pid.readline().strip('\r\n')
			pid.close()
			self.pid = int(pidstr)
		except Exception:
			self.pid = None
		return self.pid

	def is_running(self):
		self.read_pid()
		if self.pid is None:
			return False
		# very linuxish...
		if not os.path.isdir('/proc/{0}'.format(self.pid)):
			return False
		try:
			pid = open('/proc/{0}/cmdline'.format(self.pid), 'r')
			cmdline = pid.readline()
			pid.close()
			fields = cmdline.split('\0')
			if fields[0] == BtSyncAgent.BINARY:
				return True
			return False
		except Exception:
			return False

