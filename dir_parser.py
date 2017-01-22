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
# three-item dictionary: the key 'name' having as its associated value the
# name of a file or directory, the key 'type' having as its value either
# 'dir' or 'file', and the key 'body' containing the contents of the
# file or directory.
#
#  * If an item is a directory, the three-item dictionary looks like this:
#
#        { 'name': 'the directory name', 'type': 'dir', 'body': [ ... ] }
#
#  * If an item is a file, the two-item dictionary looks like this:
#
#        { 'name': 'the file name', 'type': 'file', 'body': content }
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
#  * {'name': 'abc', 'type': 'dir', 'body': []} if 'name' is an empty directory
#
#  * {'name': 'abc', 'type': 'dir', 'body': [ ...dicts... ] if it's not empty
#
#  * {'name': 'abc', 'type': 'file', 'body': ''} if the file is empty
#
#  * {'name': 'abc', 'type': 'file', 'body': '...string...'} if the file
#      contains text but not code
#
#  * {'name': 'abc', 'type': 'file', 'body': { elements } } if the file
#      contains code
#
#  * {'name': 'abc', 'type': 'file', 'body': None} if the file is ignored
#
# When it comes to non-code text files, if the file is not literally plain
# text, Elementizer extracts the text from it.  It currently converts the
# following formats: HTML, Markdown, AsciiDoc, reStructuredText, RTF, and
# Textile.  It does this by using a variety of utilities such as
# BeautifulSoup to convert the formats to plain text, and post-processes the
# result using various heuristics to create text that is hopefully easier for
# subsequent tools (like NLTK) to interpret as normal text.
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
sys.path.append('../cataloguer')
sys.path.append('../common')

from utils import *
from file_parser import file_elements
from content_inferencer import *

if not os.environ.get('NTLK_DATA'):
    nltk.data.path.append('../../other/nltk/3.2.2/nltk_data/')


# Global constants.
# .............................................................................

_content_check_size    = 512
_max_file_size         = 1024*1024
_extreme_max_file_size = 5*1024*1024

# This next URL is from:
# http://daringfireball.net/2010/07/improved_regex_for_matching_urls
# https://gist.github.com/gruber/8891611
URL_REGEX = r"""(?i)\b((?:https?:(?:/{1,3}|[a-z0-9%])|[a-z0-9.\-]+[.](?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)/)(?:[^\s()<>{}\[\]]+|\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\))+(?:\([^\s()]*?\([^\s()]+\)[^\s()]*?\)|\([^\s]+?\)|[^\s`!()\[\]{};:'".,<>?«»“”‘’])|(?:(?<!@)[a-z0-9]+(?:[.\-][a-z0-9]+)*[.](?:com|net|org|edu|gov|mil|aero|asia|biz|cat|coop|info|int|jobs|mobi|museum|name|post|pro|tel|travel|xxx|ac|ad|ae|af|ag|ai|al|am|an|ao|aq|ar|as|at|au|aw|ax|az|ba|bb|bd|be|bf|bg|bh|bi|bj|bm|bn|bo|br|bs|bt|bv|bw|by|bz|ca|cc|cd|cf|cg|ch|ci|ck|cl|cm|cn|co|cr|cs|cu|cv|cx|cy|cz|dd|de|dj|dk|dm|do|dz|ec|ee|eg|eh|er|es|et|eu|fi|fj|fk|fm|fo|fr|ga|gb|gd|ge|gf|gg|gh|gi|gl|gm|gn|gp|gq|gr|gs|gt|gu|gw|gy|hk|hm|hn|hr|ht|hu|id|ie|il|im|in|io|iq|ir|is|it|je|jm|jo|jp|ke|kg|kh|ki|km|kn|kp|kr|kw|ky|kz|la|lb|lc|li|lk|lr|ls|lt|lu|lv|ly|ma|mc|md|me|mg|mh|mk|ml|mm|mn|mo|mp|mq|mr|ms|mt|mu|mv|mw|mx|my|mz|na|nc|ne|nf|ng|ni|nl|no|np|nr|nu|nz|om|pa|pe|pf|pg|ph|pk|pl|pm|pn|pr|ps|pt|pw|py|qa|re|ro|rs|ru|rw|sa|sb|sc|sd|se|sg|sh|si|sj|Ja|sk|sl|sm|sn|so|sr|ss|st|su|sv|sx|sy|sz|tc|td|tf|tg|th|tj|tk|tl|tm|tn|to|tp|tr|tt|tv|tw|tz|ua|ug|uk|us|uy|uz|va|vc|ve|vg|vi|vn|vu|wf|ws|ye|yt|yu|za|zm|zw)\b/?(?!@)))"""


# Main functions
# .............................................................................

def dir_elements(path):
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
            if empty_file(file):
                item = {'name': file, 'type': 'file', 'body': ''}
            elif ignorable_file(file):
                item = {'name': file, 'type': 'file', 'body': None}
            elif python_file(file):
                item = {'name': file, 'type': 'file', 'body': file_elements(file)}
            elif text_file(file):
                if excessively_large_file(file):
                    item = {'name': file, 'type': 'file', 'body': None}
                else:
                    item = {'name': file, 'type': 'file', 'body': extract_text(file)}
            else:
                item = {'name': file, 'type': 'file', 'body': None}
            contents.append(item)
        for dir in subdirs:
            contents.append(dir_elements(dir))
        return {'name': path, 'type': 'dir', 'body': contents}


# Utilities.
# .............................................................................

_common_puretext_extensions = [
    '.1st',
    '.ascii',
    '.readme',
    '.text',
    '.txt',
]

_common_text_markup_extensions = [
    '.asciidoc',
    '.adoc',
    '.asc',
    '.creole',
    '.htm',
    '.html5',
    '.html',
    '.htmls',
    '.markdown',
    '.md',
    '.mdown',
    '.mdwn',
    '.mediwiki',
    '.mkdn',
    '.pod',
    '.rdoc',
    '.rtf',
    '.rst',
    '.textile',
    '.wiki',
]

_common_ignorable_files = [
    '*~',
    '.#*',
    '.*.swp',
    '.bak',
    '.pyc',
]


def empty_file(filename):
    return os.path.getsize(filename) == 0


def ignorable_file(filename):
    return (not os.path.isfile(filename)
            or os.path.getsize(filename) > _extreme_max_file_size
            or any(fnmatch(filename, pat) for pat in _common_ignorable_files))


def python_file(filename):
    name, ext = os.path.splitext(filename.lower())
    if ext == '.py':
        return True
    if ext == '':
        # No extension, but might still be a python file.
        try:
            return 'Python' in magic.from_file(filename).decode('utf-8')
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
    if ext in _common_puretext_extensions or ext in _common_text_markup_extensions:
        return True
    elif not is_code_file(filename):
        return probably_text(filename)
    else:
        return False


def probably_text(filename):
    try:
        return 'text' in magic.from_file(filename).decode('utf-8')
    except Exception as e:
        # msg('*** unable to check content of {}: {}'.format(filename, e))
        return False


def extract_text(filename, encoding='utf-8'):
    name, ext = os.path.splitext(filename.lower())
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    try:
        with open(filename, 'r', encoding=encoding) as file:
            if ext in _common_puretext_extensions or ext == '':
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


def convert_plain_text(text):
    # Remove URLs.
    text = re.sub(URL_REGEX, '', text)
    # Remove obvious divider lines, like lines of dashes.
    text = re.sub(r'^[-=_]+$', '', text, flags=re.MULTILINE)
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
        el.replace_with(re.sub(URL_REGEX, '', el.text))
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
            li.replace_with(re.sub(URL_REGEX, '', li.text))
            # Add commas after list elements if they have no other
            # punctuation, and add a period after the last element.
            if i == last and li.string:
                li.append('.')
            elif li.string and not li.string.rstrip().endswith(('.', ',', ':', ';')):
                li.append(',')

    text = re.sub(r'\n', ' ', ''.join(soup.find_all(text=True)))
    return text


def is_url(text):
    for word in text.split(' '):
        if urlparse(word.strip()).scheme:
            return True


def omit_common_extra_characters(s):
    return s.sub('[0-9!_-+=@ ]', '')


def clean_text(seq):
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


# Quick test driver.
# .............................................................................

if __name__ == '__main__':
    msg(dir_elements(sys.argv[1]))
