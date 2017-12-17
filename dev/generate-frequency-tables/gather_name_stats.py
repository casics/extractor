#!/usr/bin/env python3
'''
gather_name_stats.py: create a table of name frequencies

This is used to create a frequency table for common components of identifiers
used in program code.  Currently it only handles Python code and ignores
anything else found in a source code base.

This takes a list of GitHub repository numbers and iterates over them to (1)
extract code identifier components, (2) count unique components for each
repository, and (3) add the counts across the entire set of repositories to
produce a frequency table.  So for example, if repository 10101010 has
functions named 'foo' and 'bar' somewhere in ther Python code, and repository
20202020 has functions named 'foo' and 'biff' somewhere in their Python code,
then the final frequency table will have foo: 2, bar: 1, biff: 1.

The components of identifiers are extracted using CASICS Extractor by using
the identifiers found in class definitions, function calls, function names,
variable names, and imports, and then splitting the identifiers using
safe_simple_split() from CASICS Spiral.  The splitter uses a safe approach
that splits by hard delimiters such as underscores, digits, and forward camel
case ONLY, i.e., lower-to-upper case transitions.  This means it will split
fooBarBaz into 'foo', 'Bar' and 'Baz', and foo2bar into 'foo' and 'bar, but
it won't change SQLlite or similar identifiers.  It will also not split
identifies that have multiple adjacent uppercase letters anywhere in them,
because doing so is risky if the uppercase letters are not an acronym.
(For example, it won't split something like 'aFastNDecoder'.)

Additionally, single-character names are discarded, as are names longer than
30 characters (because the longest non-coined English word is 30 characters,
according to https://en.wikipedia.org/wiki/Longest_word_in_English).

This script exists to make the frequency table used for some splitter
algorithms in CASICS Spiral, notably the Samurai algorithm by Enslen et al.

Authors
-------

Michael Hucka <mhucka@caltech.edu>

Copyright
---------

Copyright (c) 2017 by the California Institute of Technology.  This software
was developed as part of the CASICS project, the Comprehensive and Automated
Software Inventory Creation System.  For more, visit http://casics.org.

'''

import code
from   collections import defaultdict
from   datetime import datetime
import IPython
import logging
import operator
import os
import plac
import pprint
import Pyro4
import setproctitle
import socket
import sys
from   time import sleep
from   timeit import default_timer as timer

try:
    sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))
except:
    sys.path.append("..")
    sys.path.append("../..")

from extractor.extractor_client import *
from common.data_helpers import flatten


# Global constants
# .............................................................................

_min_name_length = 2
_max_name_length = 30


# From Spiral
# .............................................................................
# We could import Spiral instead, but current Spiral is unfinished because I
# need the frequency table that this generates, so Spiral is not in a good
# state to install.  (A chicken-and-egg problem.)  These functions are short
# enough that I decided to copy-paste them here. -- MH

_hard_split_chars = '~_.:0123456789'
_hard_splitter    = str.maketrans(_hard_split_chars, ' '*len(_hard_split_chars))
_two_capitals     = re.compile(r'[A-Z][A-Z]')
_camel_case       = re.compile(r'((?<=[a-z])[A-Z])')

def safe_camelcase_split(identifier):
    '''Split identifiers by forward camel case only, i.e., lower-to-upper case
    transitions.  This means it will split fooBarBaz into 'foo', 'Bar' and
    'Baz', but it won't change SQLlite or similar identifiers.  Does not
    split identifies that have multiple adjacent uppercase letters.'''
    if re.search(_two_capitals, identifier):
        return [identifier]
    return re.sub(_camel_case, r' \1', identifier).split()

def safe_simple_split(identifier):
    '''Split identifiers by hard delimiters such as underscores, digits, and
    forward camel case only, i.e., lower-to-upper case transitions.  This
    means it will split fooBarBaz into 'foo', 'Bar' and 'Baz', and foo2bar
    into 'foo' and 'bar, but it won't change SQLlite or similar identifiers.
    Does not split identifies that have multiple adjacent uppercase
    letters anywhere in them, because doing so is risky if the uppercase
    letters are not an acronym.  Example: aFastNDecoder -> ['aFastNDecoder'].
    Contrast this to simple_split('aFastNDecoder'), which will produce
    ['a', 'Fast', 'NDecoder'] even though "NDecoder" may be more properly split
    as 'N' 'Decoder'.
    '''
    parts = str.translate(identifier, _hard_splitter).split(' ')
    return list(flatten(safe_camelcase_split(token) for token in parts))


# Main code
# .............................................................................
# Basic idea

def gather_name_frequencies(repo_ids, lang, uri, key, recache, log):
    extractor = Extractor(uri, key)
    names = defaultdict(int)
    for id in repo_ids:
        if not id:
            log.info('Ignoring blank line')
            continue
        log.info('Getting elements for {}'.format(id))
        elements = extractor.get_elements(id, recache=recache, filtering='minimal')
        if not elements:
            log.warn('*** Nothing returned by extractor for {}'.format(id))
            continue
        names_in_repo = unique_names(elements['elements'])
        if names_in_repo:
            # Take every symbol and do a safe split, and merge the result.
            expanded = []
            for name in names_in_repo:
                expanded += safe_simple_split(name)
            for name in expanded:
                length = len(name)
                if length >= _min_name_length and length <= _max_name_length:
                    names[name] += 1
        else:
            log.warn('*** Empty list of names from {}'.format(id))
    return sorted(names.items(), key=operator.itemgetter(1), reverse=True)


def unique_names(elements):
    results = unique_names_recursive(elements)
    return list(set(results)) if results else []


def unique_names_recursive(elements):
    names = []
    if 'type' in elements and elements['type'] == 'dir':
        # This will be a list of dictionaries.
        for item in elements['body']:
            if item['type'] == 'dir':
                names += unique_names_recursive(item)
            else:
                if 'code_language' in item and item['code_language'] == 'Python':
                    # print('file {}'.format(item['name']))
                    body = item['body']
                    names += list(value[0] for value in body['calls'])
                    names += list(value[0] for value in body['functions'])
                    names += list(value[0] for value in body['classes'])
                    names += list(value[0] for value in body['variables'])
                    names += list(value[0] for value in body['imports'])
    return names


# Entry point
# .............................................................................

# Argument annotations are: (help, kind, abbrev, type, choices, metavar)
# Plac automatically adds a -h argument for help, so no need to do it here.
@plac.annotations(
    uri     = ('URI to connect to',    'option', 'u'),
    key     = ('crypto key',           'option', 'k'),
    recache = ('invalidate the cache', 'flag',   'r'),
    file    = 'file of repo identifiers',
)

def run(key=None, uri=None, recache=False, *file):
    '''Test gather_word_stats.py.'''
    if len(file) < 1:
        raise SystemExit('Need a file as argument')
    log = Logger(sys.argv[0], console=True).get_log()
    log.set_level('debug')
    filename = file[0]
    if not os.path.exists(filename):
        raise ValueError('File {} not found'.format(filename))

    log.info('Reading identifiers from {}'.format(filename))
    with open(filename) as f:
        id_list = f.read().splitlines()

    log.info('Gathering name frequencies')
    freq = gather_name_frequencies(id_list, 'Python', uri, key, recache, log)
    print(tabulate_frequencies(freq))


# Start the user interface.
# .............................................................................

if __name__ == '__main__':
    plac.call(run)
