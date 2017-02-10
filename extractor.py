#!/usr/bin/env python3.4
#
# @file    extractor.py
# @brief   Network server for returning parsed contents of repositories
# @author  Michael Hucka
#
# <!---------------------------------------------------------------------------
# Copyright (C) 2015 by the California Institute of Technology.
# This software is part of CASICS, the Comprehensive and Automated Software
# Inventory Creation System.  For more information, visit http://casics.org.
# ------------------------------------------------------------------------- -->

import code
from   datetime import datetime
import IPython
import logging
import os
import plac
import Pyro4
import setproctitle
import socket
import sys
from   time import sleep
from   timeit import default_timer as timer

sys.path.append('../database')
sys.path.append('../common')

from utils import *
from file_parser import *
from dir_parser import *
from logger import *
from text_extractor import *
from human_language import *

# The following sets up Pyro4 to print full traces when exceptions occur.
# See https://pythonhosted.org/Pyro4/tutorials.html#phase-3-final-pyro-version

sys.excepthook = Pyro4.util.excepthook


# Global constants.
# .............................................................................

_default_port      = 9999
_default_repo_root = '/srv/repositories'


# Module library interface.
# .............................................................................

class Extractor(object):
    def __init__(self, uri, key, log=None):
        self._uri = uri
        self._key = key
        self._extractor = Pyro4.Proxy(uri)
        self._extractor._pyroHmacKey = key
        self._log = log if log else Logger().get_log()


    def _reconnect(self):
        try:
            self._extractor._pyroReconnect(tries=10)
            return True
        except Exception:
            self._log.error('Lost connection to server: {}'.format(err))
            return False


    def _sanity_check_id(self, id):
        if not isinstance(id, int) and not isinstance(id, str):
            raise ValueError('Arg must be an int or a string: {}'.format(id))


    def get_status(self):
        return self._extractor.get_status()


    def get_repo_path(self, id):
        self._sanity_check_id(id)
        try:
            return self._extractor.get_repo_path(id)
        except Pyro4.errors.ConnectionClosedError:
            # Network connection lost.
            self._log.error('Network connection lost: {}'.format(err))
            return []
        except Exception as err:
            self._log.error('Exception: {}'.format(err))
            self._log.error('------ Pyro traceback ------')
            self._log.error(''.join(Pyro4.util.getPyroTraceback()))
            return ''


    def get_elements(self, id, recache=False):
        self._sanity_check_id(id)
        try:
            return self._extractor.get_elements(id, recache)
        except Pyro4.errors.ConnectionClosedError:
            # Network connection lost.
            self._log.error('Network connection lost: {}'.format(err))
            return []
        except Exception as err:
            self._log.error('Exception: {}'.format(err))
            self._log.error('------ Pyro traceback ------')
            self._log.error(''.join(Pyro4.util.getPyroTraceback()))
            return []


    def get_words(self, id, filetype='all', recache=False):
        self._sanity_check_id(id)
        try:
            return self._extractor.get_words(id, filetype, recache)
        except Pyro4.errors.ConnectionClosedError:
            # Network connection lost.
            self._log.error('Network connection lost: {}'.format(err))
            return []
        except Exception as err:
            self._log.error('Exception: {}'.format(err))
            self._log.error('------ Pyro traceback ------')
            self._log.error(''.join(Pyro4.util.getPyroTraceback()))
            return []


# Client/server application.
# .............................................................................

def main(key=None, client=False, logfile=None, loglevel=None, uri=None,
         foreground=False, hostname=None, port=_default_port, root=None,
         server=False, print_config=False):

    if not key:
        raise SystemExit('Must provide a crypto key.')
    if server and client:
        raise SystemExit('Cannot use both options -s and -c at the same time.')
    if not server and not client:
        client = True

    if client:
        log = Logger(file=logfile, console=True).get_log()
    else:
        log = Logger('Pyro4', 'extractor.log', console=foreground).get_log()
    if loglevel:
        log.set_level(loglevel)
    log.debug('main: root = {}, logfile = {}, key = {}, port = {}, uri = {}'
              .format(root, logfile, key, port, uri))

    hmac = str.encode(key)              # Convert to bytes
    if server:
        if not root:
            root = _default_repo_root
        if not os.path.isdir(root):
            log.fail('Cannot find root dir {}'.format(root))
        log.info('Root dir is {}'.format(root))

        host = hostname if hostname else socket.getfqdn()
        try:
            port = int(port)
            if not (0 < port < 65536):
                raise ValueError()
        except ValueError:
            log.fail('Port number must be an integer between 1 and 65535')

        log = Logger('Pyro4').get_log()
        log.info('Forking server on host {}'.format(host))
        log.info('Using port number {}'.format(port))
        log.info('Using root of repos: {}'.format(root))
        if not foreground:
            pid = os.fork()
            setproctitle.setproctitle(os.path.realpath(__file__))
            if pid != 0:
                log.info('Forked Extractor daemon as process {}'.format(pid))
                sys.exit()
            os.setsid()
        Pyro4.config.DETAILED_TRACEBACK = True
        Pyro4.config.COMMTIMEOUT = 0.0
        Pyro4.config.MAX_RETRIES = 10
        with Pyro4.Daemon(host=host, port=port) as daemon:
            daemon._pyroHmacKey = hmac
            handler = ExtractorServer(daemon, host, port, root, log)
            uri = daemon.register(handler, 'extractor')
            log.info('-'*60)
            log.info('Daemon running with URI = {}'.format(uri))
            log.info('-'*60)
            sys.stdout = log.log_stream()
            daemon.requestLoop()

    if client:
        if not uri:
            raise SystemExit('Need a URI if running as a client')

        log.info('Running as client with URI {}'.format(uri))
        if root:
            log.info('Ignoring inapplicable option --root.  Continuing.')

        extractor = Extractor(uri, hmac)

        # Drop into REPL and let the user do interact with the remote server.

        banner = '''Available commands:
    extractor.get_status()
    extractor.get_repo_path(id)
    extractor.get_elements(id)
    extractor.get_words(id, filetype='all', recache=False)
'''

        IPython.embed(banner1=banner)

    log.info('Exiting.')


@Pyro4.expose
class ExtractorServer(object):
    def __init__(self, daemon, host, port, repo_root, logger):
        self._daemon   = daemon
        self._host     = host
        self._port     = port
        self._root_dir = repo_root
        self._log      = logger


    def _log_action(self, msg):
        self._log.info('INVOKED: ' + msg)


    def shutdown(self):
        self._log_action('shutdown')
        self._daemon.shutdown()


    def get_status(self):
        self._log_action('get_status')
        msg = 'host = {}, port = {}, root = {}'.format(
            self._host, self._port, self._root_dir)
        return(msg)


    def get_repo_path(self, id):
        self._log_action('get_repo_path({})'.format(id))
        return generate_path(self._root_dir, id)


    def get_elements(self, id, recache=False):
        self._log_action('get_elements({}, recache={})'.format(id, recache))
        if isinstance(id, int) or (isinstance(id, str) and id.isdigit()):
            path = generate_path(self._root_dir, id)
        elif isinstance(id, str):
            path = os.path.join(self._root_dir, id)
        else:
            self._log.error('Arg must be an int or a string: {}'.format(id))
            raise ValueError('Arg must be an int or a string: {}'.format(id))
        return dir_elements(path, recache)


    def get_words(self, id, filetype='all', recache=False):
        self._log_action('get_words({}, filetype="{}", recache={})'
                         .format(id, filetype, recache))
        elements = self.get_elements(id, recache)
        return all_words(elements, filetype, recache)


# Entry point
# .............................................................................
# Argument annotations are: (help, kind, abbrev, type, choices, metavar)
# Plac automatically adds a -h argument for help, so no need to do it here.

main.__annotations__ = dict(
    key          = ('(required) crypto key',                   'option', 'k'),
    client       = ('act as client',                           'flag',   'c'),
    logfile      = ('log file',                                'option', 'l'),
    loglevel     = ('log level: "debug" or "info"',            'option', 'L'),
    uri          = ('(client) URI to connect to',              'option', 'u'),
    foreground   = ('(server) stay in foreground',             'flag',   'f'),
    hostname     = ('(server) hostname',                       'option', 'n'),
    port         = ('(server) port to listen on',              'option', 'p'),
    root         = ('(server) root directory of repositories', 'option', 'r'),
    server       = ('act as server',                           'flag',   's'),
)

if __name__ == '__main__':
    plac.call(main)
