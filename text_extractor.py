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
from   multiprocessing import Process, Manager
import nltk
import operator
import os
import pickle
import plac
import pprint
import re
import subprocess
import sys
import tempfile
import textile
from   time import sleep
from   timeit import default_timer as timer
from   tokenize import tokenize, COMMENT, STRING, NAME
from   nltk.tokenize.punkt import PunktSentenceTokenizer, PunktParameters, PunktLanguageVars
from   nltk.tokenize.api import TokenizerI
import nltk.data
import unicodedata

sys.path.append('../database')
sys.path.append('../detector')
sys.path.append('../cataloguer')
sys.path.append('../common')
sys.path.append('../splitters')

from utils import *

import constants
from   content_inferencer import *
from   human_language import *
from   logger import *
from   dir_parser import *
from   simple_splitters import *
from   samurai import samurai_split

if not os.environ.get('NTLK_DATA'):
    nltk.data.path.append('../../other/nltk/3.2.2/nltk_data/')


# Main functions
# .............................................................................

def extract_text(filename, encoding='utf-8', retried=False):
    name, ext = os.path.splitext(filename.lower())
    locale.setlocale(locale.LC_ALL, 'en_US.UTF-8')
    log = Logger().get_log()
    try:
        with open(filename, 'r', encoding=encoding, errors='replace') as file:
            if ext in constants.common_puretext_extensions:
                log.info('extracting text from pure text file {}'.format(filename))
                return clean_plain_text(file.read())
            elif ext in ['.md', '.markdown', '.mdwn', '.mkdn', '.mdown']:
                # Testing showed better text output results using markdown
                # module than using pypandoc.  Don't know why, don't care.
                log.info('extracting text from markdown file {}'.format(filename))
                html = markdown.markdown(file.read(), output_format='html4')
                return convert_html(html)
            elif ext.startswith('.htm'):
                log.info('extracting text from HTML file {}'.format(filename))
                return convert_html(file.read())
            elif ext in ['.asciidoc', '.adoc', '.asc']:
                log.info('extracting text from AsciiDoc file {}'.format(filename))
                html = html_from_asciidoc_file(filename)
                return convert_html(html)
            elif ext in ['.rst']:
                log.info('extracting text from rST file {}'.format(filename))
                html = html_from_pandoc(filename)
                return convert_html(html)
            elif ext in ['.rtf']:
                log.info('extracting text from RTF file {}'.format(filename))
                html = html_from_rtf_file(filename)
                return convert_html(html)
            elif ext in ['.textile']:
                log.info('extracting text from Textile file {}'.format(filename))
                html = textile.textile(file.read())
                return convert_html(html)
            elif ext in ['.tex']:
                log.info('extracting text from LaTeX/TeX file {}'.format(filename))
                html = html_from_pandoc(filename)
                return convert_html(html)
            elif ext in ['.docx', '.odt']:
                log.info('extracting text from office {} file {}'
                          .format(ext, filename))
                html = html_from_pandoc(filename)
                return convert_html(html)
            elif ext in ['.texi', '.texinfo']:
                log.info('extracting text from TeXinfo file {}'.format(filename))
                html = html_from_texinfo_file(filename)
                return convert_html(html)
            # Turns out pypandoc can't handle .org files, though Pandoc can.
            # elif ext in ['.org']:
            #     log.debug('extracting text from org-mode file {}'.format(filename))
            #     html = html_from_pandoc(filename)
            #     return convert_html(html)
            elif ext[1:].isdigit():
                log.info('extracting text from *roff file {}'.format(filename))
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
        return None
    except Exception as e:
        log.error('*** unable to extract text from {}: {}'
                  .format(os.path.join(os.getcwd(), filename), e))
        return None

_common_ignored_regexp = r'\(c\)|::|:-\)|:\)|:-\(|:-P|<3|->|-->'
_common_ignored        = re.compile(_common_ignored_regexp, re.IGNORECASE)
_divider_line          = re.compile(r'^\W*[-=_.+^*#~]{2,}\W*$', flags=re.MULTILINE)
_multiple_blank_line   = re.compile(r'\n[ \t]*\n\n+')
_two_newlines          = re.compile(r'(?<!\n)\n(?=[^\n])', flags=re.MULTILINE)
_multiple_spaces       = re.compile(r'\s+')

_rst_tags_regexp       = r'(:param|:return|:type|:rtype)'
_rst_tags              = re.compile(_rst_tags_regexp, flags=re.IGNORECASE)

# Common punctuation that doesn't get a period after it.
# Note the next line is filled with special non-ascii characters.
# Some of these look like they have spaces in them, but they don't!
_okay_ending_chars     = ('-', '–', '—', '…', '?', '!', '.', ',', ':', ';',
                          '‚', '‼', '⁇', '⁈', '⁉︎', '：', '；', '．', '，')
_okay_endings = re.compile(r'([^'+''.join(_okay_ending_chars)+r'])([ \t]*)\n\n',
                           flags=re.MULTILINE)

def clean_plain_text(text):
    '''Do limited cleaning of text that appears in Python code.'''

    # Remove obvious divider lines, like lines of repeated dashes.
    text = re.sub(_divider_line, ' ', text)
    # Compress multiple blank lines.
    text = re.sub(_multiple_blank_line, '\n\n', text)
    # Turn single newlines into spaces.
    text = re.sub(_two_newlines, ' ', text)

    # Don't bother going further if it's not written in a Western-style language.
    if human_language(text) not in ['en', 'fr', 'cs', 'cu', 'cy', 'da', 'de',
                                    'es', 'fi', 'fr', 'ga', 'hu', 'hy', 'is',
                                    'it', 'la', 'nb', 'nl', 'no', 'pl', 'pt',
                                    'ro', 'sk', 'sl', 'sv', 'tr', 'uk', 'eo']:
        return text.strip()

    # Get rid of funky Unicode characters
    text = unicodedata.normalize('NFKD', text)
    # Massage Sphinx style doc patterns to make it more clear where
    # sentence boundaries would be.
    text = re.sub(_rst_tags, r'\n\n\1', text)
    # Remove random other things that are useless to us.
    text = re.sub(_common_ignored, '', text)
    # If there are two newlines in a row, treat it like a paragraph break,
    # and see if the text prior to that point has an ending period.  If it
    # doesn't, add one, on the heuristic basis that it's likely a sentence end.
    text = re.sub(_okay_endings, r'\1.\2\n\n', text)
    # Compress multiple spaces into one.
    text = re.sub(_multiple_spaces,  ' ', text)
    # Strip blank space at the beginning and end of the whole thing.
    return text.strip()


# Note that NLTK abbreviations must be specified without the final period.
# Also make sure they are in lower case.
_common_abbrevs = set([
    "adm", "ala", "ariz", "ark", "aug", "b.c", "bancorp", "bhd",
    "brig", "bros", "co", "corp", "cos", "ca", "calif", "capt",
    "cie", "cmdr", "co", "col", "colo", "conn", "corp", "cos",
    "cpl", "d-mass", "d.c", "dec", "del", "dept", "dr", "e.g",
    "etc", "ex", "exch", "feb", "fla", "fri", "ga", "gen", "gov",
    "inc", "ill", "inc", "ind", "jan", "jansz", "jos", "jr", "kan",
    "ky", "l.a", "la", "lt", "ltd", "maj", "mass", "md", "messrs",
    "mfg", "mich", "minn", "miss", "mo", "mon", "mr", "mrs", "ms",
    "mt", "n.c", "n.j", "n.y", "nfatc", "neb", "nev", "no", "nos",
    "nov", "o.j", "oct", "okla", "ont", "ore", "p.t", "pa", "ph",
    "prof", "prop", "pty", "r.i", "r.j", "rep", "reps", "rev",
    "s.c", "sat", "sen", "sens", "sep", "sept", "sgt", "sol", "sr",
    "st", "sun", "tenn", "tex", "thu", "tue", "u.k", "u.n", "u.s",
    "va", "vt", "w.j", "w.va", "wash", "wed", "wis", "wyo", "a.m",
    "cit", "def", "ed", "eds", "e.g", "etc", "ft", "i.e", "op",
    "p.m", "pp", "sc", "v", "vs",
])

_odd_chars         = '|<>&+=$%^'
_odd_char_splitter = str.maketrans(_odd_chars, ' '*len(_odd_chars))
_stray_punct       = re.compile('["`\',]')
_max_word_length   = 80

# Contractions can't be done entirely by regexp.  You need to use POS tagging
# to disambiguate some cases.  However, I believe the following are unique
# and so we can do them safely.  This list is based in part on the list at
# https://en.wikipedia.org/wiki/Wikipedia%3aList_of_English_contractions
# available on 2017-02-06.  An archived copy of that page is available in the
# Internet Archive and http://archive.is.

# FIXME: handling case sensitivity this way is stupid. Should avoid the
# tests here and instead use code to fix up the case of the match, like what
# they do in http://www.clips.uantwerpen.be/BiographTA/tokenizer.py

_common_contractions = [
    (r"Ain[’']t"                                             , 'Is not'),
    (r"ain[’']t"                                             , 'is not'),
    (r"([Aa])mn[’']t"                                        , '\g<1>m not'),
    (r'([Cc])annot'                                          , '\g<1>an not'),
    (r"([Dd])oesn[’']t"                                      , '\g<1>oes not'),
    (r"([Gg])onna"                                           , '\g<1>oing to'),
    (r"([Ii])[’']m"                                          , '\g<1> am'),
    (r"([Ii])t[’']s\s+been"                                  , '\g<1>t has been'),
    (r"([Ii])t[’']s\s+not"                                   , '\g<1>t is not'),
    (r"([Ii])sn[’']t\s+([Ii]t|[Tt]hat|[Tt]his|[Ss]he|[Hh]e)" , '\g<1>s \g<2> not'),
    (r"([Ll])et[’']s"                                        , '\g<1>et us'),
    (r"([Oo])[’']clock"                                      , '\g<1>f the clock'),
    (r"([Oo])l[’']"                                          , '\g<1>ld'),
    (r"([Ss])han[’']t"                                       , '\g<1>hall not'),
    (r"([Tt])hey[’']d[’']ve"                                 , '\g<1>hey would have'),
    (r"([Ww])ho[’']d[’']ve"                                  , '\g<1>ho would have'),
    (r"([Ww])on[’']t[’']ve"                                  , '\g<1>ill not have'),
    (r"([Ww])here[’']d"                                      , '\g<1>here did'),
    (r"([Ww])hy[’']d"                                        , '\g<1>hy did'),
    (r"([Yy])[’']all"                                        , '\g<1>ou all'),
    (r"([Yy])a[’']ll"                                        , '\g<1>ou all'),

    (r"([Aa])ren[’']t\s+([Yy]ou|[Tt]hey|[Ww]e)"              , '\g<1>re \g<2> not'),
    (r"([Aa])ren[’']t\s+([Ii])"                              , '\g<1>m \g<2> not'),
    (r"([Aa])ren[’']t"                                       , '\g<1>re not'),

    (r"([Cc])an[’']t\s+([Yy]ou|[Tt]hey|[Ww]e)"               , '\g<1>an \g<2> not'),
    (r"([Cc])an[’']t\s+([Ii])"                               , '\g<1>an \g<2> not'),
    (r"([Cc])an[’']t"                                        , '\g<1>an not'),

    (r"([Dd])idn[’']t\s+([Yy]ou|[Tt]hey|[Ww]e)"              , '\g<1>id \g<2> not'),
    (r"([Dd])idn[’']t\s+([Ii])"                              , '\g<1>id \g<2> not'),
    (r"([Dd])idn[’']t"                                       , '\g<1>id not'),

    (r"([Dd])on[’']t\s+([Yy]ou|[Tt]hey|[Ww]e)"               , '\g<1>o \g<2> not'),
    (r"([Dd])on[’']t\s+([Ii])"                               , '\g<1>o \g<2> not'),
    (r"([Dd])on[’']t"                                        , '\g<1>o not'),

    (r"([Ww])on[’']t\s+([Ii])"                               , '\g<1>ill \g<2> not'),
    (r"([Ww])on[’']t\s+([Yy]ou|[Tt]hey|[Ww]e)"               , '\g<1>ill \g<2> not'),
    (r"([Ww])on[’']t"                                        , '\g<1>ill not'),

    (r"[’']cause"                                            , 'because'),
    (r"[’']nother"                                           , 'another'),
    (r"[’']em"                                               , 'them'),
    (r"[’']till"                                             , 'until'),
    (r"[’']tis"                                              , 'it is'),
    (r"[’']twas"                                             , 'it was'),
    (r"(\w+)[’']ve"                                          , '\g<1> have'),
    (r"(\w+)[’']re"                                          , '\g<1> are'),
    (r"(\w+)[’']ll"                                          , '\g<1> will'),
    (r"(\w+)n[’']t"                                          , '\g<1> not'),
    (r"(\w+)[’']d"                                           , '\g<1> would'),
]

# These work for some cases, but the problem is there are many more words
# that could go in the placeholders.  This is thus incomplete, and I'm
# not sure if it's a good idea to do some random set of cases and not other.
#
# (r"([Tt]hat|[Ww]hat|[Ii]t|[Ww]ho|[Ss]he|[Hh]e|[Ss]ome(one|thing))'s been"           , '\g<1> has been'),
# (r"([Tt]hat|[Ww]hat|[Ii]t|[Ww]ho|[Ss]he|[Hh]e|[Ss]ome(one|thing))'s(\s+\w+\s+)been" , '\g<1> has\g<2>been'),
# (r"([Tt]hat|[Ww]hat|[Ii]t|[Ww]ho|[Ss]he|[Hh]e|[Ss]ome(one|thing))'s(\s+\w+\s+)done" , '\g<1> has\g<2>done'),
# (r"([Tt]hat|[Ww]hat|[Ii]t|[Ww]ho|[Ss]he|[Hh]e|[Ss]ome(one|thing))'s(\s+\w+\s+)a"    , '\g<1> is\g<2>a'),
# (r"([Tt]hat|[Ww]hat|[Ii]t|[Ww]ho|[Ss]he|[Hh]e|[Ss]ome(one|thing))'s not"            , '\g<1> is not'),
# (r"([Tt]hat|[Ww]hat|[Ii]t|[Ww]ho|[Ss]he|[Hh]e|[Ss]ome(one|thing))'s got"            , '\g<1> has'),
# (r"([Tt]hat|[Ww]hat|[Ii]t|[Ww]ho|[Ss]he|[Hh]e|[Ss]ome(one|thing))'s"                , '\g<1> is'),

class ModifiedPunktLanguageVars(PunktLanguageVars):
    # Treat ':' as sentence-ending.  This leads to more natural sentence
    # tokenization, IMHO.  It changes the interpretation of dependent vs.
    # independent clauses, but we do not do analysis that depends on that,
    # so it's irrelevant to us.
    sent_end_chars = ('.', '?', '!', ':')

def tokenize_text(seq):
    '''Tokenizes a string containing one or more sentences, and returns a
    list of lists, with the outer list representing sentences and the inner
    lists representing tokenized words within each sentence.  This does not
    remove stop words or do more advanced NL processing.'''

    def only_words(sent):
        # Takes a list and returns a version with only plausible words.
        return [w for w in sent if is_word(w)]

    def clean_words(sent):
        # Takes a list of words and cleans them to remove stray punctuation.
        return [re.sub(_stray_punct, '', word) for word in sent]

    # Replace common contractions that are safe to replace.
    replacer = RegexpReplacer(_common_contractions)
    text = replacer.replace(seq)
    # Compress multiple blank lines into one.
    text = re.sub(r'\n+', '\n', text)
    # Remove URLs.
    text = re.sub(constants.url_compiled_regex, '', text)
    # Split words at certain characters that are not used in normal writing.
    text = str.translate(text, _odd_char_splitter)
    # Split the text into sentences.
    punkt_vars = ModifiedPunktLanguageVars()
    punkt_param = PunktParameters()
    punkt_param.abbrev_types = _common_abbrevs
    sentence_splitter = PunktSentenceTokenizer(punkt_param, lang_vars=punkt_vars)
    sentences = sentence_splitter.tokenize(text, realign_boundaries=True)
    # Tokenize each sentence individually.
    sentences = [nltk.word_tokenize(sent) for sent in sentences]
    # Filter out items that don't have any letters in them, or are too long.
    sentences = [only_words(sent) for sent in sentences]
    # Remove embedded quote characters & other oddball characters in strings.
    sentences = [clean_words(sent) for sent in sentences]
    # Remove blanks and return the result
    sentences = [x for x in sentences if x]
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
        name = elements['name']
        if ignorable_filename(name):
            log.debug('Skipping ignorable file: {}'.format(name))
            return []
        elif elements['body'] != None and len(elements['body']) == 0:
            log.debug('Skipping empty file: {}'.format(name))
            return []
        elif not elements['text_language']:
            log.debug('Skipping unhandled file type: {}'.format(name))
            return []
        elif elements['text_language'] not in ['en', 'unknown']:
            log.info('Skipping non-English file {}'.format(name))
            return []
        elif elements['body'] == None:
            log.warn('Unexpected empty body for {}'.format(name))
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


def all_identifiers(wrapper, recache=False, splitter=simple_split):
    '''Take a recursive directory/file elements dictionary and return all
    identifiers (class names, variable names, function names, function calls,
    imported module names) along with the number of occurrences of each.  The
    value returned by this function is a list of tuples of the form:
       (['part1', 'part2', ...], N)
    where N is the frequency.  Identifiers are split into parts using the
    function given as argument 'splitter'.  The parts of the split are saved
    as a list, so the first part of the tuple is ['part1', 'part2', ...].
    This returns cached results if any exist and the argument 'recache'
    is not True.
    '''

    log = Logger().get_log()
    if 'full_path' not in wrapper:
        log.debug('Missing "full_path" key in dictionary')
        return None

    full_path = wrapper['full_path']
    cached_ids = cached_value(full_path, 'all_identifiers')
    if cached_ids:
        if recache:
            log.debug('ignoring cached all_identifiers for {}'.format(full_path))
        else:
            log.debug('returning cached all_identifiers for {}'.format(full_path))
            return cached_ids
    else:
        log.debug('no cached all_identifiers found for {}'.format(full_path))

    elements = wrapper['elements']
    words = all_identifiers_recursive(elements, splitter=splitter)

    log.debug('caching all_identifiers for {}'.format(full_path))
    save_cached_value(full_path, 'all_identifiers', words)

    return words


def all_identifiers_recursive(elements, splitter):
    log = Logger().get_log()

    if not elements:
        log.warn('Empty elements -- no words returned')
        return []
    elif 'body' not in elements:
        log.warn('Missing "body" key in elements dictionary -- skipping')
        return []

    identifiers = []
    if elements['type'] == 'file':
        name = elements['name']
        if ignorable_filename(name):
            log.debug('Skipping ignorable file: {}'.format(name))
            return []
        elif elements['body'] != None and len(elements['body']) == 0:
            log.debug('Skipping empty file: {}'.format(name))
            return []
        elif not elements['code_language']:
            log.debug('Skipping unhandled file type: {}'.format(name))
            return []
        elif elements['code_language'] not in ['Python']:
            log.debug('Skipping non-Python file type: {}'.format(name))
            return []
        elif elements['body'] == None:
            log.warn('Unexpected empty body for {}'.format(name))
            return []
        identifiers = identifiers + extract_code_identifiers(elements['body'],
                                                             splitter=splitter)
    else:
        for item in elements['body']:
            identifiers = identifiers + all_identifiers_recursive(item, splitter)
    identifiers = [x for x in identifiers if x]
    return identifiers


# Utility classes.
# .............................................................................

# Code from https://github.com/japerk/nltk3-cookbook/blob/master/replacers.py

class RegexpReplacer(object):
    """ Replaces regular expression in a text.
    >>> replacer = RegexpReplacer()
    >>> replacer.replace("can't is a contraction")
    'cannot is a contraction'
    >>> replacer.replace("I should've done that thing I didn't do")
    'I should have done that thing I did not do'
    """
    def __init__(self, patterns):
        self.patterns = [(re.compile(regex), repl) for (regex, repl) in patterns]

    def replace(self, text):
        s = text
        for (pattern, repl) in self.patterns:
            s = re.sub(pattern, repl, s)
        return s

# Word-testing function and associated regexp's.

_letter         = re.compile(r'[a-zA-Z]')
_nonword_letter = re.compile(r"[^-'_.a-zA-Z]")
_repeated_char  = re.compile(r'(.)\1{4,}')
_repeated_seq   = re.compile(r'(.)\1{2,}(.)\2{2,}')
_repeated_pat3  = re.compile(r'(.)(.)(.)\1\2\3\1\2\3')
_repeated_pat4  = re.compile(r'(.)(.)(.)(.)\1\2\3\4\1\2\3\4')
_dna            = re.compile(r'[atgc]{6,}', re.I)
_rna            = re.compile(r'[augc]{6,}', re.I)
_imb            = re.compile(r'[adft]{31,}', re.I)
_alphabet       = re.compile(r'abcdefghijklmno', re.I)
_random_nonword = re.compile(r'[bcdfghjklmnpqrstvwxzy]{9,}', re.I)

def is_word(token):
    # Returns true if 'token' is plausibly a word.
    return (token
            and len(token) <= _max_word_length
            # Must have at least one letter.
            and re.search(_letter, token)
            # Ignore tokens that have un-text-like characters in them.
            and not re.search(_nonword_letter, token)
            # Ignore tokens containing strings of 5 or more repeated chars.
            # (Has to be 5 because roman numerals can have 4 I's or M's.)
            and not re.search(_repeated_char, token)
            # Ignore things that look like DNA or RNA sequences (!).
            # This is kind of conservative to avoid catching other things.
            # E.g.: "baggage", "Atacama", "attachment", "datatable".
            and not re.search(_dna, token)
            and not re.search(_rna, token)
            # Ignore USPS Intelligent Mail Barcode (IMb) barcodes.
            and not re.search(_imb, token)
            # Ignore what looks like the alphabet.
            and not re.search(_alphabet, token)
            # Ignore repeating shit like "aaabbb".
            and not re.search(_repeated_seq, token)
            and not re.search(_repeated_pat3, token)
            and not re.search(_repeated_pat4, token)
            # Random sequences
            and not (re.search(_random_nonword, token) and len(token) >= 50))


# Utility functions.
# .............................................................................

def extract_text_words(body):
    '''Tokenizes text in 'body' and mildly normalizes the text, for example
    to expand some contractions like "let's".  Removes URLs, mail addresses,
    and words that have non-ASCII characters or no letters at all.  Splits
    tokens at non-letter characters, including numbers, hyphens, underscores,
    slashes and quotes.  Does not change capitalization of words.  Splits
    pure, forward camel-case identifiers and treats them as individual words:
    'fooBar' -> 'foo', 'bar'.
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
    # Do strict camel case splitting: this is relatively safe for identifiers
    # like 'handleFileUpload' and yet won't screw up 'GPSmodule'.
    return list(flatten(safe_camelcase_split(w) for w in words))


def extract_code_words(body):
    # Look in the header, comments and docstrings.
    words = []
    if body['header']:
        words = extract_text_words(body['header'])
    for element in ['comments', 'docstrings']:
        for chunk in body[element]:
            words = words + extract_text_words(chunk)
    return words


def extract_code_identifiers(body, splitter):
    ids = []
    for element in ['classes', 'imports', 'variables', 'functions', 'calls']:
        for id, count in body[element]:
            ids.append((splitter(id), count))
    return ids


def html_from_pandoc(filename):
    '''Convert asciidoc file to HTML.'''
    # Gave up on pypandoc because I ran into a file that caused it to never
    # finish.  The problem was that pandoc itself never finished on the file
    # -- must be some bug.  Anyway, attempting to run pypandoc inside a
    # python subprocess and kill that after a timeout didn't work: it left
    # a pandoc process looping in the background.  (See the code at the end
    # of this file.)  So finally after hours of struggling, I gave up and went
    # the route of a normal subprocess and a timeout.

    full_path = os.path.join(os.getcwd(), filename)
    cmd = ['pandoc', '--to=html5', '--ascii', full_path]
    return output_from_external_converter(cmd)


def output_from_external_converter(cmd, timeout=20):
    log = Logger().get_log()
    log.debug(' '.join(cmd))
    (status, output, errors) = shell_cmd(cmd, max_time=timeout)
    if status == 0:
        return output
    elif status == -9:
        log.error('*** {} killed after {}s timeout'.format(cmd[0], timeout))
        return None
    else:
        log.error('*** call to {} failed: {}'.format(cmd[0], errors))
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
            if not el.text.rstrip().endswith(_okay_ending_chars):
                el.append('.')

    for el in soup.find_all('p'):
        # Add periods at the ends of paragraphs if necessary.
        if not el.text.rstrip().endswith(_okay_ending_chars):
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
                if li.string and not li.string.rstrip().endswith(_okay_ending_chars):
                    if i == last:
                        li.append('.')
                    else:
                        li.append(',')

    for el in soup.find_all('dl'):
        for d in soup.find_all('dt'):
            if d.string and not d.string.rstrip().endswith(_okay_ending_chars):
                d.append(':')
        for d in soup.find_all('dd'):
            if d.string and not d.string.rstrip().endswith(_okay_ending_chars):
                d.append('.')

    for table_element in ['th', 'td']:
        for el in soup.find_all(table_element):
            if el.string and not el.string.rstrip().endswith(_okay_ending_chars):
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
    if lowercase == 'all':
        word_list = [w.lower() for w in word_list]
    elif lowercase == 'capitalized':
        word_list = [w.lower() if w.istitle() else w for w in word_list]
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
    log = Logger(os.path.splitext(sys.argv[0])[0], console=True).get_log()
    log.set_level(loglevel)
    target = input[0]
    if not os.path.exists(target):
        raise ValueError('{} not found'.format(target))
    log.info('Running dir_elements')
    e = dir_elements(target, recache=recache)
    # log.info('Running all_words')
    # w = all_words(e, recache=recache)
    log.info('Running all_identifiers')
    i = all_identifiers(e, recache=recache)
    if debug:
        import ipdb; ipdb.set_trace()
    if ppr:
        pprin.pprint(i)
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



# .............................................................................
# Saving for reference

# The following doesn't work. A pandoc process is left looping in the
# background, consuming 100% of a cpu core.

# log = Logger().get_log()
# full_path = os.path.join(os.getcwd(), filename)

# def pandoc_runner():
#     log.debug('running pypandoc on {}'.format(full_path))
#     output['output'] = pypandoc.convert_file(full_path, to='html')

# with Manager() as manager:
#     output = manager.dict()
#     output['output'] = ''
#     p = Process(target=pandoc_runner)
#     p.daemon = True
#     try:
#         p.start()
#         if p.is_alive():
#             p.join(max_time)
#         if p.is_alive():
#             log.error('*** pandoc killed after {}s timeout'.format(max_time))
#             p.terminate()
#     except Exception as err:
#         log.error('*** pypandoc subprocess exception {}'.format(err))
#     finally:
#         return output['output']
