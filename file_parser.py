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
import re
import sys
import token
from tokenize import *

sys.path.append('../database')
sys.path.append('../common')

from utils import *
from text_converter import *


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
                import ipdb; ipdb.set_trace()
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


class ElementCollector(ast.NodeVisitor):
    '''AST node visitor for creating lists of elements that we care about.'''

    def __init__(self):
        self.imports   = []
        self.classes   = []
        self.functions = []
        self.variables = []
        self.comments  = []
        self.strings   = []
        self.calls     = []


    def operation_on_variable(self, name):
        return any(name in x for x in self.variables)

    def generic_visit(self, node):
        super(ElementCollector, self).generic_visit(node)


    def visit_Str(self, node):
        if not ignorable_string(node.s):
            self.strings.append(node.s)


    def visit_Assign(self, node):
        for thing in node.targets:
            name_visitor = NameVisitor()
            name_visitor.visit(thing)
            name = name_visitor.name
            if not ignorable_name(name):
                self.variables.append(name)
        self.visit(node.value)


    def visit_Call(self, node):
        callvisitor = NameVisitor()
        callvisitor.visit(node.func)
        if not ignorable_name(callvisitor.name):
            self.calls.append(callvisitor.name)
        for thing in node.args:
            self.visit(thing)


    def visit_FunctionDef(self, node):
        if not ignorable_name(node.name):
            self.functions.append(node.name)
        # Treat function parameter names as vars.
        for arg in node.args.args:
            if not ignorable_name(arg.arg):
                self.variables.append(arg.arg)
        # Process the body.
        for thing in node.body:
            self.visit(thing)


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
                self.imports.append(node.module + '.' + alias.name)


    def visit_Expr(self, node):
        self.visit(node.value)


    def visit_ClassDef(self, node):
        if not ignorable_name(node.name):
            self.classes.append(node.name)
        # Process the body.
        for thing in node.body:
            self.visit(thing)


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

    # Pass #1: use tokenize to find and store comments.

    stream = io.FileIO(filename)
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
        docstring = thing.replace('"', '')
        if header:
            header = header + ' ' + docstring
        else:
            header = docstring
        (kind, thing, _, _, line) = next(tokens)
    else:
        restart_point = stream.tell() - len(line)

    if header:
        header = header.strip()

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

    # Pass #2: pull out remaining elements separately using the AST.  This is
    # inefficient, because we're iterating over the file a 2nd time, but our
    # efforts right now are about getting things to work any way possible.

    stream.seek(restart_point)
    tree = ast.parse(stream.read())
    collector = ElementCollector()
    collector.visit(tree)

    # Post-process some of the results from the above.
    filtered_calls = filter_variables(collector.calls, collector.variables)

    # Note: don't uniquify the header.
    elements              = {}
    # These are not given frequencies.
    elements['header']    = clean_plain_text(header)
    elements['comments']  = [clean_plain_text(c) for c in comments]
    # These are turned into ('string', frequency) tuples.
    elements['imports']   = countify(collector.imports)
    elements['classes']   = countify(collector.classes)
    elements['functions'] = countify(collector.functions)
    elements['variables'] = countify(collector.variables)
    elements['strings']   = countify([clean_plain_text(c) for c in collector.strings])
    elements['calls']     = countify(filtered_calls)
    return elements


# Quick test interface.
# .............................................................................

if __name__ == '__main__':
    import pprint
    msg(file_elements(sys.argv[1]))
