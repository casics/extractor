#!/usr/bin/env python3
#
# @file    text_extract.py
# @brief   Convert, process and extract text.
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
from   dir_parser import *
from   id_splitters import *

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
                log.debug('Extracting text from markdown file {}'.format(filename))
                html = markdown.markdown(file.read(), output_format='html4')
                return convert_html(html)
            elif ext.startswith('.htm'):
                log.debug('Extracting text from HTML file {}'.format(filename))
                return convert_html(file.read())
            elif ext in ['.asciidoc', '.adoc', '.asc']:
                log.debug('Extracting text from AsciiDoc file {}'.format(filename))
                html = html_from_asciidoc_file(filename)
                return convert_html(html)
            elif ext in ['.rst']:
                log.debug('Extracting text from rST file {}'.format(filename))
                html = pypandoc.convert_file(filename, to='html')
                return convert_html(html)
            elif ext in ['.rtf']:
                log.debug('Extracting text from RTF file {}'.format(filename))
                html = html_from_rtf_file(filename)
                return convert_html(html)
            elif ext in ['.textile']:
                log.debug('Extracting text from Textile file {}'.format(filename))
                html = textile.textile(file.read())
                return convert_html(html)
            elif ext in ['.tex']:
                log.debug('Extracting text from LaTeX/TeX file {}'.format(filename))
                html = pypandoc.convert_file(filename, to='html')
                return convert_html(html)
            elif ext in ['.docx', '.odt']:
                log.debug('Extracting text from office {} file {}'
                          .format(ext, filename))
                html = pypandoc.convert_file(filename, to='html')
                return convert_html(html)
            elif ext in ['.texi', '.texinfo']:
                log.debug('Extracting text from TeXinfo file {}'.format(filename))
                html = html_from_texinfo_file(filename)
                return convert_html(html)
            # Turns out pypandoc can't handle .org files, though Pandoc can.
            # elif ext in ['.org']:
            #     log.debug('Extracting text from org-mode file {}'.format(filename))
            #     html = pypandoc.convert_file(filename, to='html')
            #     return convert_html(html)
            elif ext[1:].isdigit():
                log.debug('Extracting text from *roff file {}'.format(filename))
                html = html_from_roff_file(filename)
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
        return []
    except Exception as e:
        log.error('*** unable to extract text from {} file {}: {}'
                  .format(ext, filename, e))
        return []


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
_odd_chars = '|<>&+=$%^'
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
    sentences = [[re.sub('["`\',]', '', word) for word in sent] for sent in sentences]

    # Remove blanks.
    sentences = [x for x in sentences if x]

    # Done.
    return sentences


def all_words(wrapper, filetype='all', recache=False):
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
    if 'full_path' not in wrapper:
        log.debug('Missing "full_path" key in dictionary')
        return None

    full_path = wrapper['full_path']
    cached_words = cached_value(full_path, 'all_words')
    if cached_words:
        if recache:
            log.debug('ignoring cached all_words for {}'.format(full_path))
        else:
            log.debug('returning cached all_words for {}'.format(full_path))
            return cached_words
    else:
        log.debug('no cached all_words found for {}'.format(full_path))

    elements = wrapper['elements']
    words = all_words_recursive(elements, filetype=filetype)

    log.debug('caching all_words for {}'.format(full_path))
    save_cached_value(full_path, 'all_words', words)

    return words


def all_words_recursive(elements, filetype='all'):
    log = Logger().get_log()

    if not elements:
        log.warn('Empty elements -- no words returned')
        return []
    elif 'body' not in elements:
        log.warn('Missing "body" key in elements dictionary -- skipping')
        return []

    words = []
    if elements['type'] == 'file':
        if ignorable_filename(elements['name']):
            log.debug('Skipping ignorable file: {}'.format(elements['name']))
            return []
        elif elements['body'] != None and len(elements['body']) == 0:
            log.debug('Skipping empty file: {}'.format(elements['name']))
            return []
        elif not elements['text_language']:
            log.debug('Skipping unhandled file type: {}'.format(elements['name']))
            return []
        elif elements['text_language'] not in ['en', 'unknown']:
            log.info('Skipping non-English file {}'.format(elements['name']))
            return []
        elif elements['body'] == None:
            log.warn('Unexpected empty body for {}'.format(elements['name']))
            return []

        if filetype in ['text', 'all'] and not elements['code_language']:
            words = words + extract_text_words(elements['body'])
        if filetype in ['code', 'all'] and elements['code_language']:
            words = words + extract_code_words(elements['body'])
    else:
        for item in elements['body']:
            words = words + all_words_recursive(item, filetype=filetype)
    words = [w for w in words if w]
    return words


# Utilities.
# .............................................................................

def extract_text_words(body):
    '''Tokenizes text in 'body'.  Removes URLs and other things.  Lowercases
    capitalized words but doesn't change all-caps words and mixed-case words
    that begin with a capital (e.g., XMatrix).  Splits pure camel-case
    identifiers and treats them as individual words: 'fooBar' -> 'foo',
    'bar'. Removes URLs and words that have no letters.
    '''
    words = flatten(tokenize_text(body))
    # Remove words that are URLs.
    words = [w for w in words if not re.search(constants.url_compiled_regex, w)]
    words = [w for w in words if not re.search(constants.mail_compiled_regex, w)]
    # Remove / from paths to leave individual words: /usr/bin -> usr bin
    # Also split words at hyphens and other delimiters while we're at it.
    # Also split words at numbers, e.g., "rtf2html" -> "rtf", "html".
    words = flatten(re.split(r'[-/_.:\\0123456789’*]', w) for w in words)
    # Remove words that contain non-ASCII characters.
    words = [w for w in words if is_ascii(w)]
    # Remove terms that have no letters.
    words = [w for w in words if re.search(r'[a-zA-Z]+', w)]
    # Remove terms that contain unusual characters embedded, like %s.
    words = [w for w in words if not re.search(r'[%]', w)]
    # Do naive camel case splitting: this is relatively safe for identifiers
    # like 'handleFileUpload' and yet won't screw up 'GPSmodule'.
    words = flatten(safe_camelcase_split(w) for w in words)
    # Lowercase words that are capitalized (but not others).
    words = [w.lower() if w.istitle() else w for w in words]
    return list(flatten(words))


def extract_code_words(body):
    # Look in the header, comments and docstrings.
    words = []
    if body['header']:
        words = extract_text_words(body['header'])
    for element in ['comments', 'docstrings']:
        for chunk in body[element]:
            words = words + extract_text_words(chunk)
    return words


def output_from_external_converter(cmd):
    log = Logger().get_log()
    log.debug(' '.join(cmd))
    (status, output, errors) = shell_cmd(cmd)
    if status == 0:
        return output
    else:
        raise ShellCommandException('{} failed: {}'.format(cmd[0], errors))


def html_from_asciidoc_file(filename):
    '''Convert asciidoc file to HTML.'''
    cmd = ['asciidoctor', '--no-header-footer', '--safe', '--quiet',
           '-o', '-', os.path.join(os.getcwd(), filename)]
    return output_from_external_converter(cmd)


def html_from_rtf_file(filename):
    '''Convert RTF file to HTML.'''
    # Wanted to use Python 'pyth', but it's not Python 3 compatible.  Linux
    # 'unrtf' needs to be installed on the system.
    cmd = ['unrtf', os.path.join(os.getcwd(), filename)]
    return output_from_external_converter(cmd)


def html_from_roff_file(filename):
    '''Convert Unix man page (roff) file to HTML.'''
    cmd = ['mandoc', '-Thtml', os.path.join(os.getcwd(), filename)]
    return output_from_external_converter(cmd)


def html_from_texinfo_file(filename):
    '''Convert GNU TeXinfo file to HTML.'''
    cmd = ['makeinfo', '--html', '--no-headers', '--no-split',
           '--no-number-sections', '--disable-encoding', '--no-validate',
           '--no-warn', '-o', '-', os.path.join(os.getcwd(), filename)]
    return output_from_external_converter(cmd)


# 2017-02-04 <mhucka@caltech.edu> Currently can't be used because rdoc
# generates a subdirectory with multiple files.
def html_from_rdoc_file(filename):
    '''Convert Ruby .rdoc file to HTML.'''
    cmd = ['rdoc', '-O', os.path.join(os.getcwd(), filename)]
    return output_from_external_converter(cmd)


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

    # Remove style elements.
    for el in soup.find_all('style'):
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


def word_frequencies(word_list, lowercase=False):
    from nltk.probability import FreqDist
    if lowercase:
        word_list = [w.lower() for w in word_list]
    return FreqDist(word_list).most_common()


def tabulate_frequencies(freq, format='plain'):
    from tabulate import tabulate
    return tabulate(freq, tablefmt=format)


def ignorable_filename(name):
    return any(fnmatch(name, pat) for pat in constants.common_ignorable_files)


# Quick test interface.
# .............................................................................

def run_text_extractor(debug=False, ppr=False, loglevel='info',
                       recache=False, *input):
    '''Test word_extractor.py.'''
    if len(input) < 1:
        raise SystemExit('Need an argument')
    log = Logger(sys.argv[0], console=True).get_log()
    if debug:
        log.set_level('debug')
    else:
        log.set_level(loglevel)
    target = input[0]
    if not os.path.exists(target):
        raise ValueError('{} not found'.format(target))
    log.info('Running dir_elements')
    e = dir_elements(target, recache=recache)
    log.info('Running all_words')
    w = all_words(e, recache=recache)
    if debug:
        import ipdb; ipdb.set_trace()
    if ppr:
        msg(w)
    else:
        print(tabulate_frequencies(word_frequencies(w)))

run_text_extractor.__annotations__ = dict(
    debug    = ('drop into ipdb after parsing',     'flag',   'd'),
    ppr      = ('use pprint to print result',       'flag',   'p'),
    loglevel = ('logging level: "debug" or "info"', 'option', 'L'),
    recache  = ('invalidate caches',                'flag',   'r'),
    input    = 'file or directory to process',
)

if __name__ == '__main__':
    plac.call(run_text_extractor)
