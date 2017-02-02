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

if not os.environ.get('NTLK_DATA'):
    nltk.data.path.append('../../other/nltk/3.2.2/nltk_data/')


# Global constants
# .............................................................................

# Common punctuation that doesn't get a period after it.
_okay_endings = ('-', '–', '—', '…', '?', '!', '.', ',', ':', ';',
                 # The next line is filled with special non-ascii characters.
                 # Some of these look like they have spaces, but they don't.
                 '‚', '‼', '⁇', '⁈', '⁉︎', '：', '；', '．', '，')


# Main functions
# .............................................................................

def extract_text(filename, encoding='utf-8', retried=False):
    name, ext = os.path.splitext(filename.lower())
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    log = Logger().get_log()
    try:
        with open(filename, 'r', encoding=encoding, errors='replace') as file:
            if ext in constants.common_puretext_extensions:
                return clean_plain_text(file.read())
            elif ext in ['.md', '.markdown', '.mdwn', '.mkdn', '.mdown']:
                # Testing showed better text output results using markdown
                # module than using pypandoc.  Don't know why, don't care.
                html = markdown.markdown(file.read(), output_format='html4')
                return convert_html(html)
            elif ext.startswith('.htm'):
                return convert_html(file.read())
            elif ext in ['.asciidoc', '.adoc', '.asc']:
                html = html_from_asciidoc_file(filename)
                return convert_html(html)
            elif ext in ['.rst']:
                html = pypandoc.convert_file(filename, to='html')
                return convert_html(html)
            elif ext in ['.rtf']:
                html = html_from_rtf_file(filename)
                return convert_html(html)
            elif ext in ['.textile']:
                html = textile.textile(file.read())
                return convert_html(html)
            else:
                log.info('cannot handle {} file'.format(ext))
                return None
            # FIXME missing .rdoc, .pod, .wiki, .mediawiki, .creole
    except UnicodeDecodeError:
        # File does use the encoding we tried. Try guessing actual encoding.
        # But catch if we've been here before, to prevent infinite recursion.
        if not retried:
            guess = None
            with open(filename, 'rb') as f:
                content = f.read(1024)
                guess = content and chardet.detect(content)
            if guess and 'encoding' in guess:
                if guess['encoding'] == 'ascii':
                    # Using ascii usually leads to failures. UTF-8 is safer.
                    guess['encoding'] = 'utf-8'
                return extract_text(filename, guess['encoding'], True)
        log.error('*** unconvertible encoding in file {}'.format(filename))
        return ''
    except Exception as e:
        log.error('*** unable to extract text from {} file {}: {}'
                  .format(ext, filename, e))
        return ''


_common_ignored = r'\(c\)|::|:-\)|:\)|:-\(|:-P|<3|->|-->'
_common_ignored_regex = re.compile(_common_ignored, re.IGNORECASE)

_rst_tags = r':param|:return|:type|:rtype'

def clean_plain_text(text):
    '''Do limited cleaning of text that appears in Python code.'''

    # Don't bother if it's not written in a Western-style language.
    if human_language(text) not in ['en', 'fr', 'cs', 'cu', 'cy', 'da', 'de',
                                    'es', 'fi', 'fr', 'ga', 'hu', 'hy', 'is',
                                    'it', 'la', 'nb', 'nl', 'no', 'pl', 'pt',
                                    'ro', 'sk', 'sl', 'sv', 'tr', 'uk', 'eo']:
        return text

    # Get rid of funky Unicode characters
    text = unicodedata.normalize('NFKD', text)

    # Remove obvious divider lines, like lines of repeated dashes.
    text = re.sub(r'^\W*[-=_.+^*#~]{2,}\W*$', ' ', text, flags=re.MULTILINE)

    # Compress multiple blank lines.
    text = re.sub(r'\n[ \t]*\n\n+', '\n\n', text)

    # Turn single newlines into spaces.
    text = re.sub(r'(?<!\n)\n(?=[^\n])', ' ', text, flags=re.MULTILINE)

    # Massage Sphinx style doc patterns to make it more clear where
    # sentence boundaries would be.
    text = re.sub(r'('+_rst_tags+')', r'\n\n\1', text, flags=re.IGNORECASE)

    # Remove random other things that are useless to us.
    text = re.sub(_common_ignored_regex, '', text)

    # If there are two newlines in a row, treat it like a paragraph break,
    # and see if the text prior to that point has an ending period.  If it
    # doesn't, add one, on the heuristic basis that it's likely a sentence end.
    text = re.sub(r'([^'+''.join(_okay_endings)+r'])([ \t]*)\n\n',
                  r'\1.\2\n\n', text, flags=re.MULTILINE)

    # Compress multiple spaces into one.
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\t+', ' ', text)

    # Strip blank space at the beginning and end of the whole thing.
    return text.strip()


_common_abbrevs = set(['dr', 'vs', 'mr', 'mrs', 'ms', 'prof', 'inc', 'llc',
                       'e.g', 'i.e'])
_odd_chars = '|<>&+=$%'
_odd_char_splitter = str.maketrans(_odd_chars, ' '*len(_odd_chars))

def tokenize_text(seq):
    '''Tokenizes a string containing one or more sentences, and returns a
    list of lists, with the outer list representing sentences and the inner
    lists representing tokenized words within each sentence.  This does not
    remove stop words or do more advanced NL processing.'''

    # Compress multiple blank lines into one.
    text = re.sub(r'\n+', '\n', seq)

    # Remove URLs.
    text = re.sub(constants.url_compiled_regex, '', text)

    # Split words at certain characters that are not used in normal writing.
    text = str.translate(text, _odd_char_splitter)

    # Split the text into sentences.
    punkt_param = PunktParameters()
    punkt_param.abbrev_types = _common_abbrevs
    sentence_splitter = PunktSentenceTokenizer(punkt_param)
    text = sentence_splitter.tokenize(text, realign_boundaries=True)

    # Tokenize each sentence individually.
    text = [nltk.word_tokenize(sent) for sent in text]

    # Remove terms that don't have any letters in them.
    sentences = []
    for sent in text:
        sentences.append([word for word in sent if re.search(r'[a-zA-Z]', word)])

    # Remove embedded quote characters & other oddball characters in strings.
    sentences = [[re.sub('["`\']', '', word) for word in sent] for sent in sentences]

    # Remove blanks.
    sentences = [x for x in sentences if x]

    # Done.
    return sentences


# Utilities.
# .............................................................................

def html_from_asciidoc_file(filename):
    '''Convert asciidoc file to HTML.'''
    cmd = ['asciidoctor', '--no-header-footer', '--safe', '--quiet',
           '-o', '-', os.path.join(os.getcwd(), filename)]
    log = Logger().get_log()
    log.debug(' '.join(cmd))
    (status, output, errors) = shell_cmd(cmd)
    if status == 0:
        return output
    else:
        raise ShellCommandException('asciidoctor failed: {}'.format(errors))


def html_from_rtf_file(filename):
    '''Convert RTF file to HTML.'''
    # Wanted to use Python 'pyth', but it's not Python 3 compatible.  Linux
    # 'unrtf' needs to be installed on the system.
    cmd = ['unrtf', os.path.join(os.getcwd(), filename)]
    log = Logger().get_log()
    log.debug(' '.join(cmd))
    (status, output, errors) = shell_cmd(cmd)
    if status == 0:
        return output
    else:
        raise ShellCommandException('unrtf failed: {}'.format(errors))


# After looking at a lot of real-life README files and the result of its
# conversion to text by Pandoc and other converters, I noticed that the text
# often lacks punctuation that would indicate full sentences.  For human
# readers, this is often not a problem (and depending on the final formatting
# and the individual cases, may be correct), but it's a problem for feeding
# this to natural language parsers that try to segment the text into
# sentences.  The purpose of convert_html() is to adds missing punctuation
# and do other cleanup that will hopefully help NTLK sentence parsers.

def convert_html(html):
    '''Use BeautifulSoup's API to modify the text of some elements, so that
    the result is more easily parsed into sentences by later tools.  Script
    elements and HTML comments are removed, as a <pre> and <img> elements.
    '''
    def ignorable_type(el):
        return type(el) in [bs4.Doctype, bs4.Comment, bs4.ProcessingInstruction]

    soup = bs4.BeautifulSoup(html, 'lxml')

    # If the input is not in English, we're not going to do NL processing on
    # it anyway and we can skip the rest of this process.  For speed, this
    # check only considers the first few paragraphs.
    paragraphs = soup.find_all('p')
    p_text = ''.join(p.text for p in paragraphs[1:5])
    if p_text and human_language(p_text) != 'en':
        return unsoupify(soup)

    # Remove DOCTYPEs, processing instructions, & comments.
    for el in soup.find_all(text=lambda text: ignorable_type(text)):
        el.extract()

    # Remove scripts.
    for el in soup.find_all('script'):
        el.extract()

    # Ignore pre and img because we don't have a good way of dealing with them.
    for ignorable in ['pre', 'img']:
        for el in soup.find_all(ignorable):
            el.extract()

    for htype in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        # Add periods at the ends of headings (to make them look like sentences)
        for el in soup.find_all(htype):
            if not el.text.rstrip().endswith(_okay_endings):
                el.append('.')

    for el in soup.find_all('p'):
        # Add periods at the ends of paragraphs if necessary.
        if not el.text.rstrip().endswith(_okay_endings):
            el.append('.')

    for list_type in ['ul', 'ol']:
        for el in soup.find_all(list_type):
            list_elements = el.find_all('li')
            if not list_elements:
                continue
            last = len(list_elements)
            for i, li in enumerate(list_elements, start=1):
                # Add commas after list elements if they have no other
                # punctuation, and add a period after the last element.
                if li.string and not li.string.rstrip().endswith(_okay_endings):
                    if i == last:
                        li.append('.')
                    else:
                        li.append(',')

    for el in soup.find_all('dl'):
        for d in soup.find_all('dt'):
            if d.string and not d.string.rstrip().endswith(_okay_endings):
                d.append(':')
        for d in soup.find_all('dd'):
            if d.string and not d.string.rstrip().endswith(_okay_endings):
                d.append('.')

    for table_element in ['th', 'td']:
        for el in soup.find_all(table_element):
            if el.string and not el.string.rstrip().endswith(_okay_endings):
                # This one adds a space afterwards, because for some reason
                # BS doesn't put spaces after these elements when you do the
                # find_all(text=True) at the end.
                el.append('. ')

    # Strip out all URLs anywhere.
    # 2017-01-23 Currently think this better be done while tokenizing sentences
    # for el in soup.find_all(string=constants.url_compiled_regex):
    #     el.string.replace_with(re.sub(constants.url_compiled_regex, '.', el.string))

    # Return a single text string.
    return unsoupify(soup)


def unsoupify(soup):
    '''Convert BeautifulSoup output to a text string.'''
    text = re.sub(r'\n', ' ', ''.join(soup.find_all(text=True)))
    text = unicodedata.normalize('NFKD', text)
    return text
