#!/usr/bin/env python3.4

import os
import pytest
import sys
import glob

sys.path.append('../')

from elementizer import *

tests_dir = os.path.dirname(os.path.realpath(__file__))

class TestClass:
    def test_empty_file(self):
        expected = {'strings': [], 'variables': [], 'functions': [],
                    'classes': [], 'comments': [], 'imports': [], 'header': ''}
        file = os.path.join(tests_dir, 'testdir1/emptyfile.txt')
        assert(file_elements(file) == expected)

    def test_imports_only(self):
        expected = {'strings': [], 'variables': [], 'functions': [],
                    'comments': [], 'header': '', 'classes': [],
                    'imports': ['one', 'two', 'three', 'four', 'five']}
        file = os.path.join(tests_dir, 'testdir2/importsonly.py')
        assert(file_elements(file) == expected)

    def tests_simple_file(self):
        expected = {'strings': [], 'variables': ['somevar'],
                    'functions': ['somefunction'], 'comments': [],
                    'imports': [], 'header': '', 'classes': ['SomeClass']}
        file = os.path.join(tests_dir, 'testdir2/simplefile.py')
        assert(file_elements(file) == expected)
