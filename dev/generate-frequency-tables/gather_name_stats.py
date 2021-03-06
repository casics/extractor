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

from   blist import blist
import code
from   collections import defaultdict
from   datetime import datetime
import IPython
import logging
from   multiprocessing import Pool
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
from common.path import *


# Global constants
# .............................................................................

# I tried filtering out single-character tokens, but it appears they may in
# fact have an effect in Samurai's computations.
_min_name_length = 1

# There are no normal English words longer than 30 characters, so anything
# longer is a multiword construct, and we don't want it anyway.
_max_name_length = 30


# From Spiral
# .............................................................................
# We could import Spiral instead, but current Spiral is unfinished because I
# need the frequency table that this generates, so Spiral is not in a good
# state to install.  (A chicken-and-egg problem.)  These functions are short
# enough that I decided to copy-paste them here. -- MH

_hard_split_chars = '$~_.:/'
_hard_splitter    = str.maketrans(_hard_split_chars, ' '*len(_hard_split_chars))
_two_capitals     = re.compile(r'[A-Z][A-Z]')
_camel_case       = re.compile(r'((?<=[a-z0-9])[A-Z])')

def safe_camelcase_split(identifier):
    '''Split identifiers by forward camel case only, i.e., lower-to-upper case
    transitions.  This means it will split fooBarBaz into 'foo', 'Bar' and
    'Baz', but it won't change SQLlite or similar identifiers.  Does not
    split identifies that have multiple adjacent uppercase letters.'''
    if re.search(_two_capitals, identifier):
        return [identifier]
    return re.sub(_camel_case, r' \1', identifier).split()

def simple_split(identifier):
    '''Split identifiers by hard delimiters such as underscores, and forward
    camel case only, i.e., lower-to-upper case transitions.  This means it
    will split fooBarBaz into 'foo', 'Bar' and 'Baz', and foo2bar into 'foo'
    and 'bar, but it won't change SQLlite or similar identifiers.  Unlike
    safe_simple_split(), this will split identifiers that may have sequences
    of all upper-case letters if there is a lower-to-upper case transition
    somewhere.  Example: simple_split('aFastNDecoder') will produce ['a',
    'Fast', 'NDecoder'] even though "NDecoder" may be more correctly split as
    'N' 'Decoder'.  It preserves digits and does not treat them specially.
    '''
    parts = str.translate(identifier, _hard_splitter).split()
    return list(flatten(re.sub(_camel_case, r' \1', token).split() for token in parts))


# Main code
# .............................................................................
# Basic idea

def gather_name_frequencies_local(id_list, lang, root, recache, log, threads):
    log.info('setting number of threads to {}'.format(threads))

    # Generate full paths for each thing we're given and simultaneously
    # check that the input contents are valid.
    paths = blist()
    for x in id_list:
        if x.strip() is '':
            continue
        if isinstance(x, int) or (isinstance(x, str) and x.isdigit()):
            paths.append(generate_path(root, x))
        elif isinstance(x, str):
            paths.append(os.path.join(root, x))
        else:
            log.error('Arg must be an int or a string: {}'.format(x))
            raise ValueError('Arg must be an int or a string: {}'.format(x))

    elements = blist()

    def store_elements(e):
        elements.append(e)

    log.info('Getting elements from local file system')
    pool = Pool(threads)
    for path in paths:
        pool.apply_async(dir_elements, args=(path, recache, 'minimal'),
                         callback=store_elements)
    pool.close()
    pool.join()

    log.info('Tallying frequencies')
    frequency_dict = name_frequencies(elements, log)

    log.info('Finished.')
    return frequency_dict


def gather_name_frequencies_remote(repo_ids, lang, uri, key, recache, log, threads):
    log.info('Starting ...')
    extractor = Extractor(uri, key)

    log.info('Setting number of threads to {}'.format(threads))
    extractor.set_max_threads(threads)

    log.info('Getting elements from extractor-server')
    results = extractor.get_elements(repo_ids, recache=recache, filtering='minimal')
    if not results:
        log.warn('*** Nothing returned by extractor')
        return blist()

    log.info('Tallying frequencies')
    frequency_dict = name_frequencies(results, log)

    log.info('Finished.')
    return frequency_dict


def name_frequencies(elements_list, log):
    names = defaultdict(int)
    for elements in elements_list:
        names_in_repo = unique_names(elements['elements'])
        if names_in_repo:
            # Take every symbol and do a safe split, and merge the result.
            expanded = blist()
            for name in names_in_repo:
                if not name:
                    continue
                expanded += simple_split(name)
            # Count up the number of times each symbol component appears.
            for name in expanded:
                # Normalize to pure ASCII.
                name = name.encode('utf8').decode('ascii', 'ignore')
                length = len(name)
                if length >= _min_name_length and length <= _max_name_length:
                    names[name] += 1
        else:
            log.warn('*** Empty list of names from {}'.format(elements['full_path']))
    return sorted(names.items(), key=operator.itemgetter(1), reverse=True)


def unique_names(elements):
    results = unique_names_recursive(elements)
    return list(set(results)) if results else []


def unique_names_recursive(elements):
    if not elements:
        return []
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
    uri     = ('URI to connect to',        'option', 'u'),
    key     = ('crypto key',               'option', 'k'),
    root    = ('root of repository files', 'option', 'r'),
    threads = ('max number of threads',    'option', 't'),
    recache = ('invalidate the cache',     'flag',   'x'),
    file    = 'file of repo identifiers',
)

def run(key=None, uri=None, root=None, recache=False, threads=5, *file):
    '''Test gather_word_stats.py.'''
    if len(file) < 1:
        raise SystemExit('Need a file as argument')
    if uri and root:
        raise SystemExit('Cannot use -u and -r simultaneously')
    if uri and not key:
        raise SystemExit('Need provide a crypto key with -u')

    log = Logger(sys.argv[0], console=True).get_log()
    log.set_level('debug')
    filename = file[0]
    threads = int(threads)
    if not os.path.exists(filename):
        raise ValueError('File {} not found'.format(filename))
    log.info('Reading identifiers from {}'.format(filename))
    with open(filename) as f:
        id_list = f.read().splitlines()

    if uri:
        log.info('Using remote server at {}'.format(uri))
        freq = gather_name_frequencies_remote(id_list, 'Python', uri, key, recache, log, threads)
    else:
        log.info('Using local files at {}'.format(root))
        freq = gather_name_frequencies_local(id_list, 'Python', root, recache, log, threads)

    print(tabulate_frequencies(freq))


# Start the user interface.
# .............................................................................

if __name__ == '__main__':
    plac.call(run)
