#!/usr/bin/env python3
#
# @file    dir_parser.py
# @brief   Given a directory, parse all the Python files in it.
# @author  Michael Hucka
#
# <!---------------------------------------------------------------------------
# Copyright (C) 2015 by the California Institute of Technology.
# This software is part of CASICS, the Comprehensive and Automated Software
# Inventory Creation System.  For more information, visit http://casics.org.
# ------------------------------------------------------------------------- -->

# Summary
# .............................................................................
# Given a repository id, this returns a JSON data structure containing a
# highly processed and condensed version of the directory contents of that
# repository.
#
# The outer dictionary (the value actually returned by `get_elements(...)`)
# is a wrapper with two key-value pairs: `full_path`, whose value is the full
# path to the directory on the disk, and `elements`, which is the actual
# content data.
#
# The format of the `elements` structure is simple and recursive.  Each
# element is a dictionary with a least three key-value pairs: the key 'name'
# having as its associated value the name of a file or directory, the key
# 'type' having as its value either 'dir' or 'file', and the key 'body'
# containing the contents of the file or directory.  In the case of files,
# the dictionary has three additional keys: 'text_language', for the
# predominant human language found in the text (based on the file header and
# comments), 'code_language', for the programming language (if the file is
# code), and 'status', to indicate success or failure in parsing the file.
#
#  * If an item is a directory, the dictionary looks like this:
#
#        { 'name': 'the directory name', 'type': 'dir', 'body': [ ... ] }
#
#  * If an item is a file, the dictionary looks like this:
#
#        { 'name': 'the file name', 'type': 'file', 'body': content,
#          'code_language': 'the lang', 'text_language': 'the lang',
#          'status': 'string' }
#
# In the case of a directory, the value associated with the key 'body' is a
# list that can be either empty ([]) if the directory is empty, or else a
# list of dictionaries, each of which the same basic two-element structure.
# In the case of a file, the content associated with the key 'body' can be
# one of four things: (1) an empty string, if the file is empty; (2) a string
# containing the plain-text content of the file (if the file is a non-code
# text file), (3) a dictionary containing the processed and reduced contents
# of the file (if the file is a code file), or (4) None, if the file is
# something we ignore.  Reasons for ignoring a file include if it is a
# non-code file larger than 1 MB.
#
# Altogether, this leads to the following possibilities:
#
#  * {'name': 'X', 'type': 'dir', 'body': []} if 'name' is an empty directory
#
#  * {'name': 'X', 'type': 'dir', 'body': [ ...dicts... ] if it's not empty
#
#  * {'name': 'X', 'type': 'file', 'body': '', ...} if the file is empty
#
#  * {'name': 'X', 'type': 'file', 'body': None, 'status': 'ignored' ...}
#    if the file is ignored because we don't parse that type
#
#  * {'name': 'X', 'type': 'file', 'body': '...string...', 'text_language':
#    'en', 'code_language': Node, 'status': 'success'} if the file contains
#    text in English but not code
#
#  * {'name': 'X', 'type': 'file', 'body': { elements }, 'text_language':
#    'en', 'code_language': 'Python', 'status': 'success' } if the file
#    contains Python code with English text
#
# When it comes to non-code text files, if the file is not unstructured plain
# text, Extractor extracts the text from it.  If the file contains structured
# text, it can currently convert the following formats: HTML, Markdown,
# AsciiDoc, reStructuredText, RTF, Textile, and LaTeX/TeX.  It does this by
# using a variety of utilities such as BeautifulSoup to convert the formats
# to plain text, and returns this as a single string.  In the case of a code
# file, the value associated with the 'body' key is a dictionary of
# elements described in more detail below.
#
# The text language inside files is inferred using "langid" and the value for
# the key text_language is a two-letter ISO 639-1 code (e.g., 'en' for
# English).  The language inferrence is not perfect, particularly when there
# is not much text in a file, but by examining all the text chunks in a file
# (including all the separate comments) and returning the most
# frequently-inferred language, Extractor can do a reasonable job.  If there
# is no text at all (no headers, no comments), Extractor defaults to 'en'.
#
# In the case of a code file, the value associated with the 'body' key is a
# dictionary of elements described in more detail below.
#
#  * header text (which is the entire content in case of text files)
#  * list of imports
#  * list of class names
#  * list of functions called
#  * list of function names
#  * list of variable names
#  * list of comments
#  * list of documentation strings
#  * list of strings
#
# The predominant text language of a file is reported as a two-character ISO
# language code.  E.g., 'en' for English, 'ko' for Korean, etc.  The
# assessment is based by first looking for a file header and guessing the
# language used, and if no header is found, then examining all the comments
# (as individual strings) and taking the most common language from among them.
#
# The dictionary of elements can have empty values for the various keys even
# when a file contains code that we parse (currently, Python).  This can
# happen if the file is empty or something goes badly wrong during parsing
# such as encountering a syntactic error in the code.  (The latter happens
# because the process parses code into an AST to extract the elements, and
# this can fail if the code is unparseable.)
#
# The 'status' value will reflect success or failure of parsing.  The
# possible values are:
#
#  * 'success'     -- successful parse
#  * 'error'       -- something went wrong during parsing
#  * 'empty'       -- if the file is empty
#  * 'large'       -- skipped because the file size exceeds our threshold
#  * 'ignored'     -- skipped because the file is a kind we deliberately ignore
#  * 'unsupported' -- skipped because the file is a kind we don't support (yet)
#  * 'unhandled'   -- skipped because the file is a kind we don't handle
#
# A final note about parsing code files: it is possible that the status code
# will be 'error' and yet there may be some elements returned in the file
# dictionary.  This is because extracting comments and file headers may
# succeeded but extracting the remaining file elements may fail.  In that
# case, the extractor will return what it could get.

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
import nltk
import operator
import os
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

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from common.messages import *
from common.logger import *


# Constants for this module.
# .............................................................................

_content_check_size    = 512
_max_file_size         = 1024*1024
_extreme_max_file_size = 5*1024*1024


# Main functions
# .............................................................................

def dir_elements(path, recache=False):
    from text_extractor import extract_text
    from file_parser import file_elements

    def wrapper_dict(path, elements):
        return {'full_path': path, 'elements': elements}

    log = Logger().get_log()
    full_path = os.path.join(os.getcwd(), path)

    # Check if the destination really exists and is readable to us.
    if not os.path.exists(path):
        log.warn('{} does not exist -- skipping'.format(full_path))
        return wrapper_dict(full_path, None)
    elif not os.path.isdir(path):
        log.warn('{} is not a directory -- skipping'.format(full_path))
        return wrapper_dict(full_path, None)
    elif not os.access(path, os.R_OK|os.X_OK):
        log.warn('{} unreadable -- skipping'.format(full_path))
        return wrapper_dict(full_path, None)

    cached_elements = cached_value(full_path, 'dir_elements')
    if cached_elements:
        if recache:
            log.debug('ignoring cached dir_elements for {}'.format(full_path))
        else:
            log.debug('returning cached dir_elements for {}'.format(full_path))
            return cached_elements
    else:
        log.debug('no cached dir_elements found for {}'.format(full_path))

    elements = dir_elements_recursive(path)
    wrapper = {'full_path': full_path, 'elements': elements}

    log.debug('caching results for {}'.format(full_path))
    save_cached_value(full_path, 'dir_elements', wrapper)
    return wrapper


def dir_elements_recursive(path):
    from text_extractor import extract_text
    from file_parser import file_elements

    def file_dict(filename, elements, code_lang, text_lang, explicit_status=None):
        if explicit_status:
            status = explicit_status
        else:
            if isinstance(elements, dict):
                status = elements['parse_result']
            else:
                status = 'success' if (elements and elements != '') else 'error'
        return {'name': filename, 'type': 'file', 'body': elements,
                'text_language': text_lang, 'code_language': code_lang,
                'status': status}

    # Recursive directory walker.
    full_path = os.path.join(os.getcwd(), path)
    log = Logger().get_log()
    log.info('beginning traversal of {}'.format(full_path))
    walker = os.walk(path)

    # First entry is the current directory, so skip it.
    (this_dir, subdirs, files) = next(walker)
    with cwd_preserved():
        # Make the paths relative to the given directory.
        os.chdir(path)
        contents = []
        for file in files:
            if not os.path.exists(file):
                # Can happen if something creates a temporary file in-between
                # time we call os.walk and the time we get to processing file.
                log.warn('non-existent file: {}'.format(file))
                continue
            elif excessively_large_file(file):
                log.debug('skipping large text file: {}'.format(file))
                contents.append(file_dict(file, None, None, None, 'large'))
                continue
            elif empty_file(file):
                log.debug('skipping empty file: {}'.format(file))
                contents.append(file_dict(file, '', None, None, 'empty'))
                continue
            elif ignorable_file(file):
                log.debug('skipping ignorable file: {}'.format(file))
                contents.append(file_dict(file, None, None, None, 'ignored'))
                continue
            elif python_file(file):
                elements = file_elements(file)
                lang = elements_text_language(elements)
                contents.append(file_dict(file, elements, 'Python', lang))
                continue
            elif is_code_file(file):
                log.debug('skipping currently unhandled code file: {}'.format(file))
                contents.append(file_dict(file, None, None, None, 'unsupported'))
                continue
            elif document_file(file):
                text = extract_text(file)
                lang = human_language(text)
                contents.append(file_dict(file, text, None, lang))
                continue

            # Fall-back for cases we don't handle.
            log.info('unhandled file type: {}'.format(file))
            contents.append(file_dict(file, None, None, None, 'unhandled'))
        for dir in subdirs:
            if ignorable_dir(dir):
                log.debug('skipping ignorable directory: {}'.format(dir))
            else:
                contents.append(dir_elements_recursive(dir))

    log.info('finished traversal of {}'.format(full_path))
    return {'name': path, 'type': 'dir', 'body': contents}


# Utilities.
# .............................................................................

def empty_file(filename):
    return os.path.getsize(filename) == 0


def ignorable_file(filename):
    return (not os.path.isfile(filename)
            or os.path.getsize(filename) > _extreme_max_file_size
            or any(fnmatch(filename, pat) for pat in constants.common_ignorable_files))


def ignorable_dir(dirname):
    return any(fnmatch(dirname, pat) for pat in constants.common_ignorable_dirs)


def unhandled_file(filename):
    # Need to lower-case the name in this case, because files like makefiles
    # often vary in case.
    name = filename.lower()
    return any(fnmatch(name, pat) for pat in constants.common_unhandled_files)


def python_file(filename):
    name, ext = os.path.splitext(filename.lower())
    if ext in ['.py', '.wsgi']:
        return True
    if ext == '':
        # No extension, but might still be a python file.
        try:
            return 'Python' in file_magic(filename)
        except Exception as e:
            log = Logger().get_log()
            log.error('unable to check if {} is a Python file: {}'.format(filename, e))
            log.error(e)
    return False


def excessively_large_file(filename):
    return os.path.getsize(filename) > _max_file_size


def readme_file(filename):
    basename = os.path.basename(os.path.normpath(filename)).lower()
    return 'readme' in basename or 'read me' in basename


def document_file(filename):
    if readme_file(filename):
        return True
    name, ext = os.path.splitext(filename.lower())
    if (ext in constants.common_puretext_extensions
        or ext in constants.common_text_markup_extensions
        or ext in constants.convertible_document_extensions):
        return True
    elif not is_code_file(filename):
        return probably_text(filename)
    else:
        return False


def probably_text(filename):
    try:
        return 'text' in file_magic(filename)
    except Exception as e:
        log = Logger().get_log()
        log.error('error trying to get magic for {}'.format(filename))
        log.error(e)
        return False


def elements_text_language(elements):
    if not elements:
        return 'unknown'
    strings = [x[0] for x in elements['strings']]
    comments = elements['comments']
    header = [] if not elements['header'] else [elements['header']]
    if len(header) == 0 and len(comments) == 0:
        # If it's almost entirely code, we call it English.
        return 'en'
    else:
        return majority_language(header + comments + strings)


# Quick test driver.
# .............................................................................

import plac

def run_dir_parser(debug=False, ppr=False, loglevel='debug', recache=False, *file):
    '''Test dir_parser.py.'''
    if len(file) < 1:
        raise SystemExit('Need a directory as argument')
    log = Logger(os.path.splitext(sys.argv[0])[0], console=True).get_log()
    if debug:
        log.set_level('debug')
    else:
        log.set_level(loglevel)
    filename = file[0]
    if not os.path.exists(filename):
        raise ValueError('Directory {} not found'.format(filename))
    e = dir_elements(filename, recache)
    if debug:
        import ipdb; ipdb.set_trace()
    if ppr:
        import pprint
        pprint.pprint(e)
    else:
        msg(e)

run_dir_parser.__annotations__ = dict(
    debug    = ('drop into ipdb after parsing',     'flag',   'd'),
    ppr      = ('use pprint to print result',       'flag',   'p'),
    loglevel = ('logging level: "debug" or "info"', 'option', 'L'),
    recache  = ('invalidate the cache',             'flag',   'r'),
    file     = 'directory to parse',
)

if __name__ == '__main__':
    plac.call(run_dir_parser)
