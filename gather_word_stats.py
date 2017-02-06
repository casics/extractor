#!/usr/bin/env python3
#
# @file    gather_word_stats.py
# @brief   We have the best words.
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

from casicsdb import *
from utils import *
from file_parser import file_elements
from dir_parser import dir_elements
from logger import *
from text_extractor import *
from extractor import Extractor


def word_frequencies_for_repos(repo_ids, lang, uri, key, lowercase=False):
    from nltk.probability import FreqDist
    log = Logger().get_log()
    extractor = Extractor(uri, key)
    words = []
    for id in repo_ids:
        if not id:
            log.info('Ignoring blank line')
            continue
        log.info('Getting words for {}'.format(id))
        words = words + extractor.get_words(id)
    if lowercase == 'all':
        log.info('Lower-casing all words.')
        words = [w.lower() for w in words]
    elif lowercase == 'capitalized':
        log.info('Lower-casing capitalized words but leaving others alone.')
        words = [w.lower() if w.istitle() else w for w in words]
    return FreqDist(words).most_common()


# Entry point
# .............................................................................
# Argument annotations are: (help, kind, abbrev, type, choices, metavar)
# Plac automatically adds a -h argument for help, so no need to do it here.

def run(key=None, uri=None, *file):
    '''Test gather_word_stats.py.'''
    if len(file) < 1:
        raise SystemExit('Need a file as argument')
    log = Logger(sys.argv[0], console=True).get_log()
    log.set_level('debug')
    filename = file[0]
    if not os.path.exists(filename):
        raise ValueError('File {} not found'.format(filename))

    log.info('Reading identifiers')
    stats = []
    with open(filename) as f:
        id_list = f.read().splitlines()

    log.info('Running word_statistics')
    freq = word_frequencies_for_repos(id_list, 'Python', uri, key)
    print(tabulate_frequencies(freq))

run.__annotations__ = dict(
    uri   = ('URI to connect to', 'option', 'u'),
    key   = ('crypto key',        'option', 'k'),
    file  = 'file of repo identifiers',
)

if __name__ == '__main__':
    plac.call(run)
