#!/usr/bin/env python3
#
# @file    extractor.py
# @brief   Network client for returning parsed contents of repositories
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

try:
    sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
except:
    sys.path.append("..")

from common.messages import *
from common.logger import *
from extractor import *

# The following sets up Pyro4 to print full traces when exceptions occur.
# See https://pythonhosted.org/Pyro4/tutorials.html#phase-3-final-pyro-version

sys.excepthook = Pyro4.util.excepthook


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


    def get_elements(self, id, recache=False, filtering='normal'):
        self._sanity_check_id(id)
        try:
            return self._extractor.get_elements(id, recache, filtering)
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


    def get_identifiers(self, id, recache=False):
        self._sanity_check_id(id)
        try:
            return self._extractor.get_identifiers(id, recache)
        except Pyro4.errors.ConnectionClosedError:
            # Network connection lost.
            self._log.error('Network connection lost: {}'.format(err))
            return []
        except Exception as err:
            self._log.error('Exception: {}'.format(err))
            self._log.error('------ Pyro traceback ------')
            self._log.error(''.join(Pyro4.util.getPyroTraceback()))
            return []
