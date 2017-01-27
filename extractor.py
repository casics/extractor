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


# Global constants.
# .............................................................................

_default_port      = 9999
_default_repo_root = '/srv/repositories'
_default_log       = 'extractor.log'


# Main body.
# .............................................................................

def main(server=False, client=False, root=None, logfile=None, key=None,
         port=_default_port, uri=None, print_config=False):
    if server and client:
        raise SystemExit('Cannot use both options -s and -c at the same time.')
    if not server and not client:
        client = True

    if key:
        hmac = str.encode(key)          # Convert to bytes
    else:
        raise SystemExit('Must provide a crypto key')

    if server:
        logger = ExtractorLogger(logfile)
        if not root:
            root = _default_repo_root
        if not os.path.isdir(root):
            logger.fail('Cannot find root dir {}'.format(root))

        host = socket.getfqdn()
        try:
            port = int(port)
            if not (0 < port < 65536):
                raise ValueError()
        except ValueError:
            logger.fail('Port number must be an integer between 1 and 65535')

        logger.info('Forking server on host {}'.format(host))
        logger.info('Using port number {}'.format(port))
        logger.info('Using root of repos: {}'.format(root))
        pid = os.fork()
        setproctitle.setproctitle(os.path.realpath(__file__))
        if pid != 0:
            logger.info('Forked Extractor daemon as process {}'.format(pid))
            sys.exit()
        os.setsid()
        with Pyro4.Daemon(host=host, port=port) as daemon:
            daemon._pyroHmacKey = hmac
            handler = ExtractorServer(daemon, host, port, root)
            uri = daemon.register(handler, 'extractor')
            logger.info('-'*50)
            logger.info('uri = {}'.format(uri))
            msg('-'*60)
            msg('Daemon running with URI = {}'.format(uri))
            msg('-'*60)
            sys.stdout = logger.get_log()
            daemon.requestLoop()

    if client:
        if not uri:
            raise SystemExit('Need a URI if running as a client')

        msg('Running as client with URI {}'.format(uri))
        if root:
            msg('Ignoring inapplicable option --root.  Continuing.')

        extractor = Pyro4.Proxy(uri)
        extractor._pyroHmacKey = hmac

        # Drop into REPL and let the user do interact with the remote server.

        banner = '''Available commands:
    extractor.get_status()
    extractor.get_dir_contents(id)
    extractor.get_repo_path(id)
'''

        IPython.embed(banner1=banner)

    msg('Exiting.')


@Pyro4.expose
class ExtractorServer(object):
    def __init__(self, daemon, host, port, repo_root):
        self._daemon   = daemon
        self._host     = host
        self._port     = port
        self._root_dir = repo_root


    def get_status(self):
        msg = 'host = {}, port = {}, root = {}'.format(
            self._host, self._port, self._root_dir)
        return(msg)


    def shutdown(self):
        msg('Shutdown command received.')
        self._daemon.shutdown()


    def get_repo_path(self, id):
        return generate_path(self._root_dir, id)


    def get_dir_contents(self, id):
        if isinstance(id, int) or (isinstance(id, str) and id.isdigit()):
            path = generate_path(self._root_dir, id)
        elif isinstance(id, str):
            path = os.path.join(self._root_dir, id)
        else:
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
        return self._extractor.get_repo_path(id)


    def get_dir_contents(self, id):
        if not isinstance(id, int) and not isinstance(id, str):
            raise ValueError('Arg must be an int or a string: {}'.format(id))
        return self._extractor.get_dir_contents(id)



# Utilities
# .............................................................................

class ExtractorLogger(object):
    quiet   = False
    logger  = None
    outlog  = None

    def __init__(self, logfile=None):
        if logfile and os.path.isfile(logfile):
            os.rename(logfile, logfile + '.old')
        self.configure_logging(logfile)


    def configure_logging(self, logfile):
        self.logger = logging.getLogger('Pyro4')
        self.logger.setLevel(logging.DEBUG)
        logging.getLogger('Pyro4').addHandler(logging.NullHandler())
        if logfile:
            handler = logging.FileHandler(logfile)
        else:
            handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.outlog = handler.stream


    def info(self, *args):
        msg = ' '.join(args)
        self.logger.info(msg)


    def fail(self, *args):
        msg = 'ERROR: ' + ' '.join(args)
        self.logger.error(msg)
        self.logger.error('Exiting.')
        raise SystemExit(msg)


    def get_log(self):
        return self.outlog



# Entry point
# .............................................................................
# Argument annotations are: (help, kind, abbrev, type, choices, metavar)
# Plac automatically adds a -h argument for help, so no need to do it here.

main.__annotations__ = dict(
    client       = ('act as client',                           'flag',   'c'),
    root         = ('(server) root directory of repositories', 'option', 'd'),
    logfile      = ('log file (default: stdout)',              'option', 'l'),
    port         = ('(server) port to listen on',              'option', 'p'),
    key          = ('(server) crypto key',                     'option', 'k'),
    server       = ('act as server',                           'flag',   's'),
    uri          = ('(client) URI to connect to',              'option', 'u'),
)

if __name__ == '__main__':
    plac.call(main)
