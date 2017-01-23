#!/usr/bin/env python3
#
# @file    text_converter.py
# @brief   Convert and post-process text
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
import unicodedata

sys.path.append('../database')
sys.path.append('../cataloguer')
sys.path.append('../common')

import constants
from utils import *
from content_inferencer import *

if not os.environ.get('NTLK_DATA'):
    nltk.data.path.append('../../other/nltk/3.2.2/nltk_data/')


# Main functions
# .............................................................................

def extract_text(filename, encoding='utf-8'):
    name, ext = os.path.splitext(filename.lower())
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    try:
        with open(filename, 'r', encoding=encoding) as file:
            if ext in constants.common_puretext_extensions:
                return convert_plain_text(file.read())
            elif ext in ['.md', '.markdown', '.mdwn', '.mkdn']:
                # Testing showed better text output results using markdown
                # module than using pypandoc.  Don't know why, don't care.
                html = markdown.markdown(file.read(), output_format='html4')
                return convert_html(html)
            elif ext.startswith('.htm'):
                return convert_html(file.read())
            elif ext in ['.asciidoc', '.adoc', '.asc']:
                html = convert_asciidoc_file(filename)
                return convert_html(html)
            elif ext in ['.rst']:
                html = pypandoc.convert_file(filename, to='html')
                return convert_html(html)
            elif ext in ['.rtf']:
                html = convert_rtf_file(filename)
                return convert_html(html)
            elif ext in ['.textile']:
                html = textile.textile(file.read())
                return convert_html(html)
            else:
                import ipdb; ipdb.set_trace()
            # FIXME missing .rdoc, .pod, .wiki, .mediawiki, .creole
    except UnicodeDecodeError:
        # File does not contain UTF-8 bytes.  Try guessing actual encoding.
        guess = None
        with open(filename, 'rb') as f:
            content = f.read(512)
            guess = content and chardet.detect(content)
        if guess and 'encoding' in guess:
            return extract_text(filename, guess['encoding'])
        else:
            msg('*** unconvertible encoding in file {}'.format(filename))
            return ''
    except Exception as e:
        msg('*** unable to extract text from {} file {}: {}'.format(ext, filename, e))
        return ''


def tokenize_text(seq):
    # Compress multiple blank lines into one.
    text = re.sub(r'\n+', '\n', seq)
    # Split the text into sentences.
    text = nltk.tokenize.sent_tokenize(text)
    # Tokenize each sentence
    text = [nltk.word_tokenize(sent) for sent in text]
    # Remove terms that have no alphanumeric characters.
    sentences = []
    for sent in text:
        sentences.append([word for word in sent if re.search(r'\w', word)])
    # Remove quote characters within strings.
    # text = [re.sub('["`\']', '', word) for word in text]
    return sentences


# Utilities.
# .............................................................................

def convert_plain_text(text):
    # Remove URLs.
    text = re.sub(constants.url_regex, ' ', text)
    # Remove obvious divider lines, like lines of dashes.
    text = re.sub(r'^[-=_]+$', ' ', text, flags=re.MULTILINE)
    # Get rid of funky Unicode characters
    text = unicodedata.normalize('NFKD', text)
    return text


def convert_asciidoc_file(in_file):
    # Convert asciidoc to HTML.
    out_file = in_file + '.__tmp__'
    cmd = 'asciidoctor --no-header-footer --safe --quiet -o {} {}'.format(out_file, in_file)
    try:
        retval = os.system(cmd)
        if retval == 0:
            with open(out_file) as f:
                text = f.read()
                return text
        else:
            msg('*** asciidoctor returned {} for {}'.format(retval, in_file))
            return ''
    finally:
        os.unlink(out_file)


def convert_rtf_file(in_file):
    # Wanted to use Python 'pyth', but it's not Python 3 compatible.  Linux
    # 'unrtf' needs to be installed on the system.
    out_file = os.path.join(os.getcwd(), in_file) + '.__tmp__'
    cmd = 'unrtf {} > {}'.format(os.path.join(os.getcwd(), in_file), out_file)
    try:
        retval = os.system(cmd)
        if retval == 0:
            with open(out_file) as f:
                text = f.read()
                return text
        else:
            msg('*** unrtf returned {} for {}'.format(retval, in_file))
            return ''
    finally:
        os.unlink(out_file)


# After looking at a lot of real-life README files and the result of its
# conversion to text by Pandoc and other converters, I noticed that the text
# often lacks punctuation that would indicate full sentences.  For human
# readers, this is often not a problem (and depending on the final formatting
# and the individual cases, may be correct), but it's a problem for feeding
# this to natural language parsers that try to segment the text into
# sentences.  The purpose of convert_html() is to adds missing punctuation
# that will hopefully help NTLK sentence parsers.

def convert_html(html):
    # Use BeautifulSoup's API to modify the text of some elements, so that
    # the result is more easily parsed into sentences by later tools.

    soup = bs4.BeautifulSoup(html, 'lxml')
    for ignorable in ['pre', 'img']:
        for el in soup.find_all(ignorable):
            # Ignore stuff we can't convert to sentences
            el.extract()

    for htype in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        # Add periods at the ends of headings (to make them look like sentences)
        for el in soup.find_all(htype):
            if not el.text.rstrip().endswith(('?', '!', ':')):
                el.append('.')

    for el in soup.find_all('p'):
        # Strip URLs inside the text.
        el.replace_with(re.sub(constants.url_regex, '', el.text))
        # Add periods at the ends of paragraphs if necessary.
        if not el.text.rstrip().endswith(('?', '!', '.', ',', ':', ';', '-', '–', '—', '↩')):
            el.append('.')

    for el in soup.find_all('ul'):
        list_elements = el.find_all('li')
        if not list_elements:
            continue
        last = len(list_elements)
        for i, li in enumerate(list_elements, start=1):
            # Strip URLs inside the text.
            li.replace_with(re.sub(constants.url_regex, '', li.text))
            # Add commas after list elements if they have no other
            # punctuation, and add a period after the last element.
            if i == last and li.string:
                li.append('.')
            elif li.string and not li.string.rstrip().endswith(('.', ',', ':', ';')):
                li.append(',')

    text = re.sub(r'\n', ' ', ''.join(soup.find_all(text=True)))
    text = unicodedata.normalize('NFKD', text)
    return text
