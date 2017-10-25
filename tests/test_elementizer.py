#!/usr/bin/env python3.4

import glob
import os
import pickle
import pytest
import sys

sys.path.append('../')

from elementizer import *

tests_dir = os.path.dirname(os.path.realpath(__file__))

class TestClass:
    def test_simple_dir(self):
        expected = ('tests/testdir1',
                    [('a.txt', 'text file content\n'),
                     ('b.py', {'imports': [], 'comments': [], 'strings': [],
                               'header': 'Python file comment.\n',
                               'classes': [], 'variables': [], 'functions': []}),
                     ('emptyfile.txt', ''),
                     ('empty_subdir', []),
                     ('nonempty_subdir',
                      [('c.py', {'imports': ['somemodule'], 'comments': [],
                                 'strings': [], 'classes': [], 'variables': [],
                                 'header': '!/usr/bin/python\nThis is another test\n',
                                 'functions': ['sillyfunction']})])])
        assert(dir_elements('tests/testdir1') == expected)


    def test_textile(self):
        # The results file is saved as a pickled Python data structure.
        # Recreate it like this (with cwd being the parent of this directory):
        #
        #   import pickle
        #   output = dir_elements('tests/testdir2')
        #   file = open('tests/test2dir.output', 'wb')
        #   pickle.dump(output, file)
        #   file.close()
        #
        with open('tests/testdir2.output', 'rb') as f:
            expected = pickle.load(f)
            assert(dir_elements('tests/testdir2') == expected)
