#!/usr/bin/env python3

import bs4
import chardet
from   datetime import datetime
from   fnmatch import fnmatch
import html2text
import locale
import io
import keyword
import magic
import markdown
import math
import operator
import os
import pickle
import plac
import pprint
import pypandoc
import re
import sys
import tempfile
import textile
from   time import sleep
from   timeit import default_timer as timer
from   tokenize import tokenize, COMMENT, STRING, NAME
import unicodedata

sys.path.append('../database')
sys.path.append('../detector')
sys.path.append('../cataloguer')
sys.path.append('../common')

from utils import *

import constants
from   content_inferencer import *
from   human_language import *
from   text_converter import *
from   logger import *
from   dir_parser import *
from   id_splitters import *


# Main body.
# .............................................................................

def word_frequencies(word_list, lowercase=False):
    from nltk.probability import FreqDist
    if lowercase:
        word_list = [w.lower() for w in word_list]
    return FreqDist(word_list).most_common()


def all_words(elements, filetype='all'):
    '''Take a recursive directory/file elements dictionary and return all
    words found in text files or as comments or headers in code files.  Some
    basic cleanup is applied: pure camel case names are split into multiple
    words, words in title case are lower-cased, uppercase and other mixed-
    case words are left unchanged, URLs are removed, words that have no
    letters are removed, but stopwords are not removed.

    Argument 'filetype' limits the files considered:
      'text' ==> only text files are read
      'code' ==> only program files are read
      'all'  ==> both text and code files

    '''

    log = Logger().get_log()
    if 'body' not in elements:
        log.debug('Missing "body" key in dictionary')
        return None
    words = []
    for item in elements['body']:
        if item['type'] == 'dir':
            words.append(all_words(item['body']))
        else:
            if ignorable_filename(item['name']):
                log.debug('Skipping ignorable file: {}'.format(item['name']))
                continue
            elif item['text_language'] not in ['en', 'unknown']:
                log.info('Skipping non-English file {}'.format(item['name']))
                continue

            if filetype in ['text', 'all'] and not item['code_language']:
                words = words + extract_text_words(item['body'])
            if filetype in ['code', 'all'] and item['code_language']:
                words = words + extract_code_words(item['body'])
    words = [w for w in words if w]
    return words


def extract_text_words(body):
    '''Lowercases capitalized words but doesn't change all-caps words and
    mixed-case words that begin with a capital (e.g., XMatrix).  Splits
    pure camel-case identifiers and treats them as individual words:
    'fooBar' -> 'foo', 'bar'. Removes URLs and words that have no letters.'''

    words = flatten(tokenize_text(body))
    # Remove words that are URLs.
    words = [w for w in words if not re.search(constants.url_compiled_regex, w)]
    words = [w for w in words if not re.search(constants.mail_compiled_regex, w)]
    # Remove / from paths to leave individual words: /usr/bin -> usr bin
    # Also split words at hyphens and other delimiters while we're at it.
    # Also split words at numbers, e.g., "rtf2html" -> "rtf", "html".
    tmp = []
    for w in words:
        tmp = tmp + re.split(r'[-/_.:\\0123456789’*]', w)
    words = tmp
    # Remove words that contain non-ASCII characters.
    words = [w for w in words if is_ascii(w)]
    # Remove terms that have no letters.
    words = [w for w in words if re.search(r'[a-zA-Z]+', w)]
    # Remove terms that contain unusual characters embedded, like %s.
    words = [w for w in words if not re.search(r'[%]', w)]
    # Do naive camel case splitting: this is relatively safe for identifiers
    # like 'handleFileUpload' and yet won't screw up 'GPSmodule'.
    tmp = []
    for w in words:
        tmp = tmp + naive_camelcase_split(w)
    words = tmp
    # Lowercase words that are capitalized (but not others).
    tmp = []
    for w in words:
        tmp.append(w.lower() if w.istitle() else w)
    words = tmp
    return words


def extract_code_words(body):
    # Look in the header, comments and docstrings.
    words = []
    if body['header']:
        words = extract_text_words(body['header'])
    for element in ['comments', 'docstrings']:
        for chunk in body[element]:
            words = words + extract_text_words(chunk)
    return words


# Utilities.
# .............................................................................

def tabulate_frequencies(freq, format='plain'):
    from tabulate import tabulate
    return tabulate(freq, tablefmt=format)


def ignorable_filename(name):
    return any(fnmatch(name, pat) for pat in constants.common_ignorable_files)


# Quick test interface.
# .............................................................................

def run_word_collector(debug=False, ppr=False, loglevel='info', *file):
    '''Test word_collector.py.'''
    if len(file) < 1:
        raise SystemExit('Need a directory as argument')
    log = Logger('word_collector', console=True).get_log()
    if debug:
        log.set_level('debug')
    else:
        log.set_level(loglevel)
    filename = file[0]
    if not os.path.exists(filename):
        raise ValueError('Directory {} not found'.format(filename))
    log.info('Running dir_elements')
    e = dir_elements(filename)
    log.info('Running all_words')
    w = all_words(e)
    log.info('Getting_word frequencies')
    f = list(word_frequencies(w))
    if debug:
        import ipdb; ipdb.set_trace()
    if ppr:
        import pprint
        pprint.pprint(f)
    else:
        print(tabulate_frequencies(f))

run_word_collector.__annotations__ = dict(
    debug    = ('drop into ipdb after parsing',     'flag',   'd'),
    ppr      = ('use pprint to print result',       'flag',   'p'),
    loglevel = ('logging level: "debug" or "info"', 'option', 'L'),
    file     = 'directory to parse',
)

if __name__ == '__main__':
    plac.call(run_word_collector)
