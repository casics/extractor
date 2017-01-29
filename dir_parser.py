#!/usr/bin/env python3.4
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
# The format of the JSON structure is simple and recursive.  Each element is
# a dictionary with a least the following key-value pairs: the key 'name'
# having as its associated value the name of a file or directory, the key
# 'type' having as its value either 'dir' or 'file', and the key 'body'
# containing the contents of the file or directory.  In the case of files,
# the dictionary has two additional keys: `'text_language'`, for the
# predominant human language found in the text (based on the file header and
# comments), and `'code_language'`, for the language of the program (if the
# file is code).
#
#  * If an item is a directory, the dictionary looks like this:
#
#        { 'name': 'the directory name', 'type': 'dir', 'body': [ ... ] }
#
#  * If an item is a file, the dictionary looks like this:
#
#        { 'name': 'the file name', 'type': 'file', 'body': content,
#          'code_language': 'the lang', 'text_language': 'the lang' }
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
# * `{'name': 'abc', 'type': 'dir', 'body': []}` if `'name'` is an empty
# * directory
#
# * `{'name': 'abc', 'type': 'dir', 'body': [ ...dicts... ]` if it's not empty
#
# * `{'name': 'abc', 'type': 'file', 'body': '', 'text_language': None,
#   'code_language': Node}` if the file is empty
#
# * `{'name': 'abc', 'type': 'file', 'body': '...string...', 'text_language':
#   'en', 'code_language': Node}` if the file contains text in English but
#   not code
#
# * `{'name': 'abc', 'type': 'file', 'body': { elements }, 'text_language':
#   'en', 'code_language': 'Python' }` if the file contains Python code with
#   English text
#
# * `{'name': 'abc', 'type': 'file', 'body': None, 'text_language': None,
#   'code_language': Node}` if the file is ignored
#
# When it comes to non-code text files, if the file is not literally plain
# text, Extractor extracts the text from it.  It currently converts the
# following formats: HTML, Markdown, AsciiDoc, reStructuredText, RTF, and
# Textile.  It does this by using a variety of utilities such as
# BeautifulSoup to convert the formats to plain text, and returns this as a
# single string.  In the case of a code file, the value associated with the
# `'body'` key is a dictionary of elements described in more detail below.
#
# The text language inside files is inferred using
# `[langid](https://github.com/saffsd/langid.py)` and the value for the key
# `text_language` is a two-letter ISO 639-1 code (e.g., `'en'` for English).
# The language inferrence is not perfect, particularly when there is not much
# text in a file, but by examining all the text chunks in a file (including
# all the separate comments) and returning the most frequently-inferred
# language, Extractor can do a reasonable job.  If there is no text at all
# (no headers, no comments), Extractor defaults to `'en'`.
#
# In the case of a code file, the value associated with the
# 'body' key is a dictionary of elements described in more detail below.
#
#  * header text (which is the entire content in case of text files)
#  * list of imports
#  * list of class names
#  * list of functions called
#  * list of function names
#  * list of variable names
#  * list of comments
#  * list of strings
#
# The predominant text language of a file is reported as a two-character ISO
# language code.  E.g., 'en' for English, 'ko' for Korean, etc.  The
# assessment is based by first looking for a file header and guessing the
# language used, and if no header is found, then examining all the comments
# (as individual strings) and taking the most common language from among them.

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

sys.path.append('../database')
sys.path.append('../detector')
sys.path.append('../cataloguer')
sys.path.append('../common')

import constants
from utils import *
from file_parser import file_elements
from content_inferencer import *
from text_converter import extract_text
from human_language import *


# Constants for this module.
# .............................................................................

_content_check_size    = 512
_max_file_size         = 1024*1024
_extreme_max_file_size = 5*1024*1024


# Main functions
# .............................................................................

def dir_elements(path):
    def file_dict(filename, body, code_lang, text_lang):
        return {'name': filename, 'type': 'file', 'body': body,
                'text_language': text_lang, 'code_language': code_lang}

    if not os.path.isdir(path):
        raise ValueError('Not a directory: {}'.format(path))
    # Recursive directory walker.
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
                continue
            elif empty_file(file):
                contents.append(file_dict(file, '', None, None))
                continue
            elif ignorable_file(file):
                contents.append(file_dict(file, None, None, None))
                continue
            elif python_file(file):
                elements = file_elements(file)
                lang = 'en'
                if elements:
                    chunks = [elements['header']] + elements['comments']
                    lang = majority_language(chunks)
                contents.append(file_dict(file, elements, 'Python', lang))
                continue
            elif text_file(file) and not excessively_large_file(file):
                text = extract_text(file)
                if text:
                    lang = human_language(text)
                    contents.append(file_dict(file, text, None, lang))
                    continue
            # Fall-back for cases we don't handle.
            contents.append(file_dict(file, None, None, None))
        for dir in subdirs:
            contents.append(dir_elements(dir))
        return {'name': path, 'type': 'dir', 'body': contents}


# Utilities.
# .............................................................................

def empty_file(filename):
    return os.path.getsize(filename) == 0


def ignorable_file(filename):
    return (not os.path.isfile(filename)
            or os.path.getsize(filename) > _extreme_max_file_size
            or any(fnmatch(filename, pat) for pat in constants.common_ignorable_files))


def python_file(filename):
    name, ext = os.path.splitext(filename.lower())
    if ext in ['.py', '.wsgi']:
        return True
    if ext == '':
        # No extension, but might still be a python file.
        try:
            return 'Python' in file_magic(filename)
        except Exception as e:
            msg('*** unable to check if {} is a Python file: {}'.format(filename, e))
    return False


def excessively_large_file(filename):
    return os.path.getsize(filename) > _max_file_size


def readme_file(filename):
    basename = os.path.basename(os.path.normpath(filename)).lower()
    return 'readme' in basename or 'read me' in basename


def text_file(filename):
    if readme_file(filename):
        return True
    name, ext = os.path.splitext(filename.lower())
    if ext in constants.common_puretext_extensions or ext in constants.common_text_markup_extensions:
        return True
    elif not is_code_file(filename):
        return probably_text(filename)
    else:
        return False


def probably_text(filename):
    try:
        return 'text' in file_magic(filename)
    except Exception as e:
        # msg('*** unable to check content of {}: {}'.format(filename, e))
        return False


# Quick test driver.
# .............................................................................

import plac

def run_dir_parser(debug=False, ppr=False, *file):
    '''Test dir_parser.py.'''
    if len(file) < 1:
        raise SystemExit('Need a directory as argument')
    filename = file[0]
    if not os.path.exists(filename):
        raise ValueError('Directory {} not found'.format(filename))
    e = dir_elements(filename)
    if debug:
        import ipdb; ipdb.set_trace()
    if ppr:
        import pprint
        pprint.pprint(e)
    else:
        msg(e)

run_dir_parser.__annotations__ = dict(
    debug = ('drop into ipdb after parsing', 'flag',   'd'),
    ppr   = ('use pprint to print result',   'flag',   'p'),
    file  = 'directory to parse',
)

if __name__ == '__main__':
    plac.call(run_dir_parser)
