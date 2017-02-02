#!/usr/bin/env python3
#
# @file    id_splitters.py
# @brief   ID splitters
# @author  Michael Hucka
#
# <!---------------------------------------------------------------------------
# Copyright (C) 2015 by the California Institute of Technology.
# This software is part of CASICS, the Comprehensive and Automated Software
# Inventory Creation System.  For more information, visit http://casics.org.
# ------------------------------------------------------------------------- -->

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
from   nltk.tokenize.punkt import PunktSentenceTokenizer, PunktParameters
import unicodedata

sys.path.append('../database')
sys.path.append('../detector')
sys.path.append('../cataloguer')
sys.path.append('../common')

from utils import *

import constants
from   content_inferencer import *
from   human_language import *
from   logger import *


# Delimiter-based splitter
# .............................................................................
#
# This does nothing fancy. It splits by explicit delimiter characters like '_'.

_delimiter_chars = '_.:'
_delimiter_splitter = str.maketrans(_delimiter_chars, ' '*len(_delimiter_chars))

def delimiter_split(identifier):
    '''Split identifier by explicit delimiters only.'''
    parts = str.translate(identifier, _delimiter_splitter).split(' ')
    parts = [p for p in parts if p]
    return parts


def naive_camelcase_split(identifier):
    '''Split identifiers by forward camel case only, i.e., lower-to-upper case
    transitions.  This means it will split fooBarBaz into 'foo', 'Bar' and
    'Baz', but it won't change SQLlite or similar identifiers.'''
    return re.sub(r'((?<=[a-z])[A-Z])', r' \1', identifier).split()
