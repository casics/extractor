#!/usr/bin/env python3
#
# @file    file_parser.py
# @brief   Parse a Python file and return a tuple of essential features.
# @author  Michael Hucka
#
# <!---------------------------------------------------------------------------
# Copyright (C) 2015 by the California Institute of Technology.
# This software is part of CASICS, the Comprehensive and Automated Software
# Inventory Creation System.  For more information, visit http://casics.org.
# ------------------------------------------------------------------------- -->

import ast
from   collections import deque, Counter
import io, keyword
import math
import operator
import os
import plac
import re
import shutil
import sys
import tempfile
import token
from   tokenize import *

sys.path.append('../database')
sys.path.append('../common')

from utils import *
from text_extractor import *
from logger import *


# Global configuration constants.
# .............................................................................

# Lot of things just don't look very interesting if they're too short.
# The next set of constants sets some thresholds.
_min_name_len = 3
_min_comment_len = 4
_min_string_len = 6

# Separator lines, or other comment lines without any text:
# Coding line at top of file is per https://www.python.org/dev/peps/pep-0263/

_comment_start    = '#'
_nontext_comment  = re.compile(r'^[^A-Za-z]+$')
_hashbang_comment = re.compile('^#!.*$')
_coding_comment   = re.compile('^[ \t\v]*.*?coding[:=]')
_vim_comment      = re.compile('^[ \t\v]*vim')
_emacs_comment    = re.compile('^[ \t\v]*-\*-[ \t]+mode:')

# Some symbols in Python code are not useful to us.
_ignorable_names = [
    # Python idioms.
    '_',

    # Python special function names.
    '__abs__', '__add__', '__and__', '__ceil__', '__cmp__', '__coerce__',
    '__complex__', '__contains__', '__copy__', '__deepcopy__', '__del__',
    '__delete__', '__delitem__', '__dir__', '__div__', '__divmod__',
    '__eq__', '__float__', '__floor__', '__floordiv__', '__format__',
    '__ge__', '__get__', '__getitem__', '__gt__', '__hash__', '__hex__',
    '__iadd__', '__iand__', '__idiv__', '__ifloordiv__', '__ilshift__',
    '__imod__', '__imul__', '__index__', '__init__', '__int__',
    '__invert__', '__ior__', '__ipow__', '__irshift__', '__isub__',
    '__iter__', '__itruediv__', '__ixor__', '__le__', '__len__', '__long__',
    '__lshift__', '__lt__', '__missing__', '__mod__', '__mul__', '__ne__',
    '__neg__', '__new__', '__nonzero__', '__oct__', '__or__', '__pos__',
    '__pow__', '__radd__', '__rand__', '__rdiv__', '__rdivmod__', '__repr__',
    '__reversed__', '__rfloordiv__', '__rlshift__', '__rmod__', '__rmul__',
    '__ror__', '__round__', '__rpow__', '__rrshift__', '__rshift__',
    '__rsub__', '__rtruediv__', '__rxor__', '__set__', '__setitem__',
    '__sizeof__', '__str__', '__sub__', '__truediv__', '__trunc__',
    '__unicode__', '__xor__', '__import__',

    # Common Python built-in functions.
    # See https://docs.python.org/3/library/functions.html
    'abs', 'all', 'any', 'ascii', 'bin', 'bool', 'bytearray', 'bytes',
    'callable', 'chr', 'classmethod', 'compile', 'complex', 'delattr',
    'dict', 'dir', 'divmod', 'enumerate', 'eval', 'exec', 'filter',
    'float', 'format', 'frozenset', 'getattr', 'globals', 'hasattr', 'hash',
    'help', 'hex', 'id', 'input', 'int', 'isinstance', 'issubclass', 'iter',
    'len', 'list', 'locals', 'map', 'max', 'memoryview', 'min', 'next',
    'object', 'oct', 'ord', 'pow', 'print', 'property', 'range',
    'repr', 'reversed', 'round', 'set', 'setattr', 'slice', 'sorted',
    'staticmethod', 'str', 'sum', 'super', 'tuple', 'type', 'vars', 'self',
    'zip',

    # Additional common Python functions.
    'add', 'get', 'join', 'startswith', 'endswith', 'strip',
    'find', 'format', 'index', 'lstrip', 'rstrip', 'replace', 'sub',
    'pop', 'popitem', 'values', 'update', 'copy', 'clear',
    'iter', 'items', 'keys', 'append', 'appendleft', 'ValueError',
    'SystemExit', 'StopIteration', 'KeyError', 'RuntimeError'
]


# Utility classes.
# .............................................................................

class ElementCollector(ast.NodeVisitor):
    '''AST node visitor for creating lists of elements that we care about.'''

    def __init__(self):
        self.imports    = []
        self.classes    = []
        self.functions  = []
        self.docstrings = []
        self.variables  = []
        self.comments   = []
        self.strings    = []
        self.calls      = []
        self._current_class    = None
        self._current_function = None

    def operation_on_variable(self, name):
        return any(name in x for x in self.variables)


    def generic_visit(self, node):
        super(ElementCollector, self).generic_visit(node)


    def visit_Str(self, node):
        if not ignorable_string(node.s):
            self.strings.append(node.s)


    def visit_List(self, node):
        if hasattr(node, 'elts'):
            for thing in node.elts:
                self.visit(thing)


    def visit_Assign(self, node):
        for thing in node.targets:
            name_visitor = NameVisitor()
            name_visitor.visit(thing)
            name = name_visitor.name
            if not ignorable_name(name):
                path = []
                if self._current_function:
                    path.append(self._current_function)
                elif self._current_class:
                    path.append(self._current_class)
                path.append(name)
                var_name = '|'.join(path)
                self.variables.append(var_name)
        self.visit(node.value)


    def visit_For(self, node):
        # The variable in a for loop is in a different scope, which means it
        # shadows any instances of the same variable name outside, which
        # means we should count it without regard to whether a variable by
        # the same name already exists.
        def iterate_tuples(tuple):
            for var in tuple:
                if hasattr(var, 'id'):
                    if not ignorable_name(var.id):
                        self.variables.append(var.id)
                elif isinstance(var, ast.Tuple):
                    iterate_tuples(var.elts)
                else:
                    self.visit(var)

        if isinstance(node.target, ast.Name):
            if not ignorable_name(node.target.id):
                self.variables.append(node.target.id)
        elif isinstance(node.target, ast.Tuple):
            iterate_tuples(node.target.elts)
        elif sinstance(node.target, ast.List):
            self.visit(node.target)
        else:
            log = Logger().get_log()
            log.error('Unexpected target type in visit_For')


    def visit_Call(self, node):
        callvisitor = NameVisitor()
        callvisitor.visit(node.func)
        if not ignorable_name(callvisitor.name):
            self.calls.append(callvisitor.name)
        for thing in node.args:
            self.visit(thing)
        for thing in node.keywords:
            name = thing.arg
            if not ignorable_name(name):
                path = []
                if self._current_function:
                    path.append(self._current_function)
                elif self._current_class:
                    path.append(self._current_class)
                path.append(name)
                arg_name = '.'.join(path)
                self.functions.append(arg_name)
            self.visit(thing.value)


    def visit_FunctionDef(self, node):
        func_name = None
        if not ignorable_name(node.name):
            path = []
            if self._current_function:
                path.append(self._current_function)
            elif self._current_class:
                path.append(self._current_class)
            path.append(node.name)
            func_name = '.'.join(path)
            self.functions.append(func_name)
        # Treat function parameter names as vars.
        for arg in node.args.args:
            if not ignorable_name(arg.arg):
                # Do the same trick with the names as we do for other vars.
                path = []
                if func_name:
                    path.append(func_name)
                elif self._current_class:
                    path.append(self._current_class)
                path.append(arg.arg)
                var_name = '|'.join(path)
                self.variables.append(var_name)
        # Check for keyword arg deafult values.
        for arg in node.args.defaults:
            self.visit(arg)
        # Check if there's a doc string.
        if len(node.body) > 0 and hasattr(node.body[0], 'value'):
            first_thing = node.body[0].value
            if isinstance(first_thing, ast.Str) and first_thing.s:
                self.docstrings.append(first_thing.s)
                # Process the body, skipping the doc string.
                for thing in node.body[1:]:
                    self._current_function = func_name
                    self.visit(thing)
                    self._current_function = None
            else:
                # Process the body.
                for thing in node.body:
                    self._current_function = func_name
                    self.visit(thing)
                    self._current_function = None
        else:
            # Process the body.
            for thing in node.body:
                self._current_function = func_name
                self.visit(thing)
                self._current_function = None


    def visit_Function(self, node):
        self.functions.append(node.name)
        # Treat function parameter names as vars.
        for arg in node.arguments.args:
            self.calls.append(arg.id)


    def visit_Import(self, node):
        # Import(names=[alias(name='io', asname=None), ...])
        for alias in node.names:
            self.imports.append(alias.name)


    def visit_ImportFrom(self, node):
        # ImportFrom(module='utils', names=[alias(name='*', asname=None)]...
        for alias in node.names:
            if alias.name == '*':
                self.imports.append(node.module)
            else:
                # 'module' is None when we have "from . import foo".
                # Skip those cases.
                if node.module:
                    self.imports.append(node.module + '.' + alias.name)


    def visit_Expr(self, node):
        self.visit(node.value)


    def visit_ClassDef(self, node):
        class_name = None
        if not ignorable_name(node.name):
            path = []
            if self._current_function:
                path.append(self._current_function)
            elif self._current_class:
                path.append(self._current_class)
            path.append(node.name)
            class_name = '.'.join(path)
            self.classes.append(class_name)
        # Check if there's a doc string.
        if len(node.body) > 0 and hasattr(node.body[0], 'value'):
            first_thing = node.body[0].value
            if isinstance(first_thing, ast.Str) and first_thing.s:
                self.docstrings.append(first_thing.s)
            # Process the body, skipping the doc string.
            for thing in node.body[1:]:
                self._current_class = class_name
                self.visit(thing)
                self._current_class = None
        else:
            # Process the body.
            for thing in node.body:
                self._current_class = class_name
                self.visit(thing)
                self._current_class = None


# NameVisitor started as code from https://suhas.org/function-call-ast-python
# but has since been heavily modified.

class NameVisitor(ast.NodeVisitor):
    '''Extract the name from a node.'''

    def __init__(self):
        self._name = deque()


    @property
    def name(self):
        return '.'.join(self._name)


    @name.deleter
    def name(self):
        self._name.clear()


    def visit_Name(self, node):
        self._name.appendleft(node.id)


    def visit_Call(self, node):
        if hasattr(node.func, 'attr'):
            self._name.appendleft(node.func.attr)
        if hasattr(node.func, 'value'):
            if hasattr(node.func.value, 'id'):
                self._name.appendleft(node.func.value.id)
            elif hasattr(node.func.value, 'attr'):
                self._name.appendleft(node.func.value.attr)
            else:
                # Chained calls like foo().bar().baz()
                self.generic_visit(node.func.value)
        elif hasattr(node.func, 'id'):
            self._name.appendleft(node.func.id)


    def visit_Attribute(self, node):
        # This gets called for variable assignments too.
        try:
            self._name.appendleft(node.attr)
            # Adding 'self' does not really provide much info, so skip it.
            if node.value.id != 'self':
                self._name.appendleft(node.value.id)
        except AttributeError:
            self.generic_visit(node)


# Utilities.
# .............................................................................

def ignorable_comment(thing):
    return (thing.strip().startswith(_comment_start) and
            (len(thing) < _min_comment_len
             or re.match(_nontext_comment, thing)
             or re.match(_coding_comment, thing)
             or re.match(_vim_comment, thing)
             or re.match(_emacs_comment, thing)
             or re.match(_hashbang_comment, thing)))


def ignorable_string(thing):
    # Only store long strings with at least one space in them,
    # in the hope that they're useful messages
    return len(thing) < _min_string_len


def ignorable_name(thing):
    return len(thing) < _min_name_len or thing in _ignorable_names


def strip_comment_char(text):
    i = 0
    max = len(text)
    while i < max and text[i] in ['#', ' ', '\t']:
        i += 1
    return text[i:]


def uniquify(seq):
    # From a posting by Dave Kirby in August 2006 to the blog here:
    # https://www.peterbe.com/plog/uniqifiers-benchmark
    seen = set()
    return [x for x in seq if x not in seen and not seen.add(x)]


def skip_to_eol(tokens):
    while True:
        (kind, _, _, _, _) = next(tokens)
        if kind == NEWLINE:
            return

def filter_variables(calls, vars):
    # If a call is an operation on a variable, like "foo.append", it's usually
    # a common Python thing like a list operation.  We remove it.
    results = []
    for call in calls:
        if not any(call.endswith(name) for name in _ignorable_names):
            results.append(call)
    return results


def countify(seq):
    return Counter(seq).most_common()


def assumes_python2(stream):
    try:
        # If AST doesn't bail, we assume it uses Python 3 syntax.
        tree = ast.parse(stream.read())
        stream.seek(0)
        return False
    except SyntaxError:
        # This almost always means that the code is in Python 2.
        return True
    except Exception as err:
        log = Logger().get_log()
        log.error('unexpected problem trying to guess if file is Python 2')
        log.error(err)
        return False


def convert_python2_file(filename):
    '''Convert Python 2 file to (limited) Python 3.  Returns the file name
    of the file containing the converted code.  The caller must delete this
    file after it's done.'''

    log = Logger().get_log()
    working_file = tempfile.NamedTemporaryFile()
    cmd = ['2to3', '-w', '-W', '-n', '-f', 'print', '-f', 'except',
           '-f', 'exec', '-f', 'funcattrs', '-f', 'unicode', '-f', 'ne',
           '-f', 'numliterals', '-f', 'paren', '-f', 'repr', '-f', 'raise',
           working_file.name]
    try:
        log.debug(cmd)
        full_path = os.path.join(os.getcwd(), filename)
        shutil.copyfile(full_path, working_file.name)
        (status, output, errors) = shell_cmd(cmd)
        if status == 0:
            log.debug('converted {}'.format(filename))
            return working_file
        elif os.path.exists(working_file.name):
            working_file.close()
        log.warn('2to3 failed to convert {} -- status {}'.format(full_path, status))
        return None
    except Exception as err:
        log = Logger().get_log()
        log.error('Exception trying to convert {}'.format(filename))
        log.error(err)
        if os.path.exists(working_file.name):
            working_file.close()
        return None


# Main body.
# .............................................................................
# This uses a 2-pass approach.  The Python 'ast' module lets us get a lot of
# things very easily, except it ignores comments.  To get the file header and
# comments inside the file, we use the Python 'tokenize' package in a separate
# pass.

def file_elements(filename):
    '''Take a Python file, return a tuple of contents.'''

    header    = ''
    comments  = []
    tmp_file  = None
    full_path = os.path.join(os.getcwd(), filename)

    def cleanup():
        stream.close()
        if tmp_file:
            log.debug('closing {}'.format(tmp_file))
            tmp_file.close()

    # Set up the dictionary.  We may end up returning only part of this
    # filled out, if we encounter errors along the way.

    elements               = {}
    elements['header']     = ''
    elements['comments']   = []
    elements['docstrings'] = []
    elements['imports']    = []
    elements['classes']    = []
    elements['functions']  = []
    elements['variables']  = []
    elements['strings']    = []
    elements['calls']      = []

    # Open the file for reading.  FileIO is needed for the Python 'ast' module.

    log = Logger('file_parser').get_log()
    log.debug('opening Python file {}'.format(full_path))
    stream = io.FileIO(filename)

    # Pass #0: account for Python 2 vs 3 syntax.
    # I haven't found another way to detect whether a script uses Python 2 or
    # 3 syntax other than to try to parse it and test for failure.  We need
    # to use ast later below, and if an input file needs Python 2, we have to
    # convert it first.  So we test first and convert at the beginning.

    if assumes_python2(stream):
        try:
            # This creates a temporary file that must be deleted later.
            log.debug('attempting to convert from Python 2')
            tmp_file = convert_python2_file(filename)
            if tmp_file:
                log.debug('conversion successful'.format(full_path))
                log.debug('closing file {}'.format(full_path))
                stream.close()
                log.debug('opening file {}'.format(tmp_file.name))
                stream = io.FileIO(tmp_file.name)
            else:
                # We thought it was Python 2 but couldn't convert it.
                # Something is wrong. Bail.
                log.warn('conversion failed -- giving up on {}'.format(full_path))
                # At this point, we still have an empty elements dictionary.
                return elements
        except Exception as err:
            log.error('error trying to detected if {} uses Python 2'.format(full_path))
            log.error(err)
            return elements

    # Pass #1: use tokenize to find and store headers and comments.

    log.debug('tokenizing {}'.format(full_path))
    tokens = tokenize(stream.readline)

    # Look for a header at the top, if any.  There are two common forms in
    # Python: a string, and a comment block.  The heuristic used here is that
    # if the first thing after any ignorable comments is a string, it's
    # assumed to be the doc string; else, any initial comments (after certain
    # special case comments, such as Unix hash-bang lines) are taken to be
    # the header; else, no header.

    for kind, thing, _, _, line in tokens:
        if kind == ENCODING:
            continue
        if ignorable_comment(thing):
            continue
        if kind != COMMENT and kind != NL:
            break
        header += strip_comment_char(thing)

    # When the above ends, 'thing' & 'kind' will be the next values to examine.
    # If it's a string, it's assumed to be the file doc string.
    # Once we do this, we'll have read the header comment or the doc string and
    # the file position will be immediately after that point.  When we do our
    # 2nd pass, we don't want to read that stuff again.  Back up over the last
    # non-string/comment thing we read, and remember where we are.

    if kind == STRING:
        restart_point = stream.tell()
        header = header + ' ' + thing.replace('"', '')
        (kind, thing, _, _, line) = next(tokens)
    else:
        restart_point = stream.tell() - len(line)

    # Iterate through the rest of the file, looking for comments.
    # This gathers consecutive comment lines together, on the premise that
    # they may contain sentences split across multiple comment lines.

    chunk = ''
    while thing != ENDMARKER:
        try:
            if kind == NL:
                pass
            elif kind == COMMENT and not ignorable_comment(thing):
                chunk = chunk + strip_comment_char(thing) + '\n'
            elif chunk:
                comments.append(chunk.strip())
                chunk = ''
            (kind, thing, _, _, _) = next(tokens)
        except StopIteration:
            break

    # This concludes what we gather without parsing the file into an AST.
    # Store the header and comments, if any.

    elements['header']     = clean_plain_text(header)
    elements['comments']   = [clean_plain_text(c) for c in comments]

    # Pass #2: pull out remaining elements separately using the AST.  This is
    # inefficient, because we're iterating over the file a 2nd time, but our
    # efforts right now are about getting things to work any way possible.

    # AST parsing failures are possible here, particularly if the file was
    # converted from Python 2.  Some programs do stuff you can't automatically
    # convert with 2to3.  If that happens, bail and return what we can.

    stream.seek(restart_point)
    try:
        log.debug('parsing into AST')
        tree = ast.parse(stream.read())
    except Exception as err:
        log.error('AST parsing failed; returning what we have so far'.format(full_path))
        cleanup()
        return elements

    # We were able to parse the file into an AST.

    collector = ElementCollector()
    collector.visit(tree)

    # We store the names of variables we find temporarily as paths separated
    # by '|' so that we can find unique variable name assignments within each
    # function or class context.  E.g., variable x in function foo is "foo|x".
    # Remove the paths now, leaving just the variable names.
    # Also filter the variables to remove things we don't bother with.

    unique_var_paths = list(set(collector.variables))
    collector.variables = [x[x.rfind('|')+1:] for x in unique_var_paths]
    filtered_calls = filter_variables(collector.calls, collector.variables)

    # We are done.  Do final cleanup and count up frequencies of some things.

    # Note that docstrings don't get frequencies associated with them.
    elements['docstrings'] = [clean_plain_text(c) for c in collector.docstrings]
    # The rest are turned into ('string', frequency) tuples.
    elements['imports']    = countify(collector.imports)
    elements['classes']    = countify(collector.classes)
    elements['functions']  = countify(collector.functions)
    elements['variables']  = countify(collector.variables)
    elements['strings']    = countify([clean_plain_text(c) for c in collector.strings])
    elements['calls']      = countify(filtered_calls)

    cleanup()
    return elements


# Quick test interface.
# .............................................................................

def run_file_parser(debug=False, ppr=False, loglevel='debug', *file):
    '''Test file_parser.py.'''
    if len(file) < 1:
        raise SystemExit('Need a file as argument')
    log = Logger('file_parser', console=True).get_log()
    if debug:
        log.set_level('debug')
    else:
        log.set_level(loglevel)
    filename = file[0]
    if not os.path.exists(filename):
        raise ValueError('File {} not found'.format(filename))
    e = file_elements(filename)
    if debug:
        import ipdb; ipdb.set_trace()
    if ppr:
        import pprint
        pprint.pprint(e)
    else:
        msg(e)

run_file_parser.__annotations__ = dict(
    debug    = ('drop into ipdb after parsing',     'flag',   'd'),
    ppr      = ('use pprint to print result',       'flag',   'p'),
    loglevel = ('logging level: "debug" or "info"', 'option', 'L'),
    file     = 'file to parse',
)

if __name__ == '__main__':
    plac.call(run_file_parser)
