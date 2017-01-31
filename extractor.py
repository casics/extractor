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
from file_parser import file_elements
from dir_parser import dir_elements
from logger import *

# The following sets up Pyro4 to print full traces when exceptions occur.
# See https://pythonhosted.org/Pyro4/tutorials.html#phase-3-final-pyro-version

sys.excepthook = Pyro4.util.excepthook


# Global constants.
# .............................................................................

_default_port      = 9999
_default_repo_root = '/srv/repositories'


# Main body.
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

        extractor = Pyro4.Proxy(uri)
        extractor._pyroHmacKey = hmac

        # Drop into REPL and let the user do interact with the remote server.

        banner = '''Available commands:
    extractor.get_status()
    extractor.get_repo_path(id)
    extractor.get_elements(id)
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


    def get_status(self):
        self._log_action('get_status')
        msg = 'host = {}, port = {}, root = {}'.format(
            self._host, self._port, self._root_dir)
        return(msg)


    def shutdown(self):
        self._log_action('shutdown')
        self._daemon.shutdown()


    def get_repo_path(self, id):
        self._log_action('get_repo_path({})'.format(id))
        return generate_path(self._root_dir, id)


    def get_elements(self, id):
        self._log_action('get_elements({})'.format(id))
        if isinstance(id, int) or (isinstance(id, str) and id.isdigit()):
            path = generate_path(self._root_dir, id)
        elif isinstance(id, str):
            path = os.path.join(self._root_dir, id)
        else:
            self._log.error('Arg must be an int or a string: {}'.format(id))
            raise ValueError('Arg must be an int or a string: {}'.format(id))
        return dir_elements(path)


class ExtractorClient(object):
    def __init__(self, uri, key):
        self._uri = uri
        self._key = key
        self._extractor = Pyro4.Proxy(uri)
        self._extractor._pyroHmacKey = str.encode(key)    # Convert to bytes


    def get_status(self):
        return self._extractor.get_status()


    def get_repo_path(self, id):
        if not isinstance(id, int) and not isinstance(id, str):
            raise ValueError('Arg must be an int or a string: {}'.format(id))
        try:
            return self._extractor.get_repo_path(id)
        except Exception as err:
            log.error('Exception: {}'.format(err))
            log.error('------ Pyro traceback ------')
            log.error(''.join(Pyro4.util.getPyroTraceback()))


    def get_elements(self, id):
        if not isinstance(id, int) and not isinstance(id, str):
            raise ValueError('Arg must be an int or a string: {}'.format(id))
        try:
            return self._extractor.get_elements(id)
        except Exception as err:
            log.error('Exception: {}'.format(err))
            log.error('------ Pyro traceback ------')
            log.error(''.join(Pyro4.util.getPyroTraceback()))


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
