CASICS Extractor
================

<img width="100px" align="right" src=".graphics/casics-logo-small.svg">

The goal of the CASICS Extractor is to extract text and features from files, and serve them over a network API to other modules that do inference.

*Authors*:      [Michael Hucka](http://github.com/mhucka)<br>
*Repository*:   [https://github.com/casics/extractor](https://github.com/casics/extractor)<br>
*License*:      Unless otherwise noted, this content is licensed under the [GPLv3](https://www.gnu.org/licenses/gpl-3.0.en.html) license.

☀ Introduction
-----------------------------

This module is a network server (_Extractor_) that is meant to run on the source code repository server.  Given a repository identifier, it can return different extracted text and features from our cached copy of that source code repository.  The network communication protocol is implemented using [Pyro4](https://pythonhosted.org/Pyro4/), a very easy-to-use Python RPC library that allows complex objects to be exchanged.

The goal of Extractor is to extract text and features from files.  It does _some_ generic cleanup of what it finds, to produce a result that (hopefully) subsequent stages can use as a more effective starting point for different processes.

⧈ Interacting with the Extractor using the API
----------------------------------------------

To call Extractor from a program, first import the module and then create an object of class `ExtractorClient` with arguments for the URI and the crypto key (in that order).  After that, the same methods above will be available on the object.  Example:

    from extractor import ExtractorClient

    extractor = ExtractorClient(uri, key)
    print(extractor.get_status())

☛ Interacting with Extractor on the command line
------------------------------------------------

The API provided by Extractor consists of a handful of methods on the RPC endpoint.  The file `extractor.py` implements a simple interactive REPL interface for exploring and testing, although calling programs can interact with the interface interface more directly.  The interactive interface in `extractor.py` can be started by providing the URI to the server instance, and a cryptographic key:

    ./extractor.py -k THE_KEY -u THE_URI

The values of `THE_KEY` and `THE_URI` are not stored anywhere and must be communicated separately.  Once the interactive interface starts up (it's just a normal IPython loop), the object `extractor` is the handle to the RPC interface.  The following are the available methods:

* `extractor.get_elements(ID)` returns the structure discussed above for the repository whose identifier is `ID`.
* `extractor.get_words(id)`: return a list of all words in both text and code files.
* `extractor.get_words(id, filetype='text')`: return a list of all words in text files, ignoring code files.
* `extractor.get_words(id, filetype='code')`: return a list of all words in code files, ignoring text files.
* `extractor.get_repo_path(ID)` returns a single string, the repository path, for a repository whose identifier is `ID`.
* `extractor.get_status()` returns a string with some information about the status of the server

❀ The formats of the text data returned by `get_words()`
--------------------------------------------------------

The extractor `get_words(...)` function returns a list of textual words found in files in a repository.  It currently only understands (1) English plain-text files, (2) files that can be converted to plain text (such as HTML and Markdown), and (3) Python code files.  It takes a repository identifier and an optional argument to tell it to limit consideration to only text or code files:

* `get_words(id)`: return a list of all words in both text and code files.
* `get_words(id, filetype='text')`: return a list of all words in text files, ignoring code files.
* `get_words(id, filetype='code')`: return a list of all words in code files, ignoring text files.

For text files, it automatically converts some structured text files and some document formats into plain text.  These are currently: HTML, Markdown, AsciiDoc, reStructured Text, RTF, TeXinfo, Textile, LaTeX/TeX, DOCX and ODT.  For code files, it uses the text it finds in the (1) file header (or file docstring, in the case of Python), (2) comments in the file, and (3) documentation strings on classes and functions.

The list of words is processed to a limited extent.  The transformations are:

* Tokenize sentences using NTLK's `PunktSentenceTokenizer`
* Remove URLs and email addresses
* Remove words that don't have any letters 
* Split words that have certain characters such as `/` and `_`
* Perform naive camel case splitting: only look for transitions from lower case to upper case, except for the first character in the string. This transforms `'fooBarBaz'` to `'foo'`, `'Bar'`, `'Baz'` but leaves things like `HTTPmodule` untouched.
* Lower-case words only if they are in title case, and leave all others alone. This changes `'Bar'` to `'bar'` but leaves things like `'HTTP'` alone.

The processes above are intended to balance the risk of incorrectly interpreting a word or term, with the need to normalize the text to _some_ degree.


✐ The format of the file/directory elements data returned by `get_elements()`
----------------------------------------------------------------------------

The Extractor function `get_elements(...)` returns a dictionary representation of all the files and subdirectories in a repository.

The outer dictionary (the value actually returned by `get_elements(...)`) is a wrapper with two key-value pairs: `full_path`, whose value is the full path to the directory on the disk, and `elements`, which is the actual content data.

The format of the `elements` structure is simple and recursive.  Each element is a dictionary with at least the following key-value pairs: the key `'name'` having as its associated value the name of a file or directory, the key `'type'` having as its value either `'dir'` or `'file'`, and the key `'body'` containing the contents of the file or directory.  In the case of files, the dictionary has two additional keys: `'text_language'`, for the predominant human language found in the text (based on the file header and comments), and `'code_language'`, for the language of the program (if the file represents code).  In summary:

* If an item is a directory, the dictionary looks like this:

        { 'name': 'the directory name', 'type': 'dir', 'body': [ ... ] }

* If an item is a file, the dictionary looks like this:

        { 'name': 'the file name', 'type': 'file', 'body': content,
          'code_language': 'the lang', 'text_language': 'the lang' }

In the case of a directory, the value associated with the key `'body'` is a list that can be either empty (`[]`) if the directory is empty, or else a list of dictionaries, each of which the same basic  structure.  In the case of a file, the content associated with the key `'body'` can be one of four things: (1) an empty string, if the file is empty; (2) a string containing the plain-text content of the file (if the file is a non-code text file), (3) a dictionary containing the processed and reduced contents of the file (if the file is a code file), or (4) `None`, if the file is something we ignore.  Reasons for ignoring a file include if it is a non-code file larger than 1 MB.

Altogether, this leads to the following possibilities:

* `{'name': 'abc', 'type': 'dir', 'body': []}` if `'name'` is an empty directory

* `{'name': 'abc', 'type': 'dir', 'body': [ ...dicts... ]` if it's not empty

* `{'name': 'abc', 'type': 'file', 'body': '', ...}` if the file is empty

* `{'name': 'abc', 'type': 'file', 'body': None, ...}` if the file is ignored because we don't support parsing that type of file (yet) or else an error occurred while trying to parse it

* `{'name': 'abc', 'type': 'file', 'body': '...string...', 'text_language': 'en', 'code_language': Node}` if the file contains text in English but not code

* `{'name': 'abc', 'type': 'file', 'body': { elements }, 'text_language': 'en', 'code_language': 'Python' }` if the file contains Python code with English text

When it comes to non-code text files, if the file is not literally plain text, Extractor extracts the text from it.  It currently converts the following formats: HTML, Markdown, AsciiDoc, reStructuredText, RTF, Textile, and LaTeX/TeX.  It does this by using a variety of utilities such as BeautifulSoup to convert the formats to plain text, and returns this as a single string.  In the case of a code file, the value associated with the `'body'` key is a dictionary of elements described in more detail below.

The text language inside files is inferred using [langid](https://github.com/saffsd/langid.py) and the value for the key `text_language` is a two-letter ISO 639-1 code (e.g., `'en'` for English).  The language inferrence is not perfect, particularly when there is not much text in a file, but by examining all the text chunks in a file (including all the separate comments) and returning the most frequently-inferred language, Extractor can do a reasonable job.  If there is no text at all (no headers, no comments), Extractor defaults to `'en'` because programming languages themselves are usually written in English.

☺︎ More information about the parsed file contents
-------------------------------------------------

The file parser attempts to reduce code files to "essentials" by throwing away most things and segregating different types of elements.  Some of the entities are just lists of strings, while others are tuples of (`'thing'`, _frequency_) in which the number of times the `'thing'` is found is counted and reported.  The elements in the dictionary are as follows:

* _Header text_. A single string, this is the text of either the comment header or (in case of Python files) a documentation string that precedes any code in the file.  If the first line of the file is a hashbang line, it is ignored.  If the content of the file prior to any actual code contains both comments and a documentation string, they are concatenated together to create the value for the header text string.

* _List of comments_.  A list of strings, representing all comment lines in the file, processed according to the scheme described in a separate section below.

* _List of docstrings_.  A list of strings, representing all class and function documentation strings, processed according to the scheme described in a separate section below.

* _List of strings_.  A list of tuples consisting of all strings longer than 6 characters (processed according to the scheme described in a separate section below), together with the number of times that string is found in the file.

* _List of imports_. A list of tuples consisting of the names of all Python libraries imported using either `import` or `from`, together with the number of times that the import is found in the file.

* _List of class names defined in the file_. A list of tuples consisting of the classes defined in the file, together with the number of times that the class definition is found in the file.  Nested class definitions are named in path notation using `'.'` to separate components: `'OuterClass.InnerClass.InnerInnerClass`'.

* _List of function names defined in the file_.  A list of tuples consisting of the functions defined in the file and the number of times they are defined in the file.  Nested function definitions and functions defined inside classes are named in path notation using `'.'` to separate components: `'SomeClass.some_function`'.

* _List of variable names defined in the file_.  A list of tuples consisting of variables defined in the file and the number of times those variables are defined in different parts of the code.  (If a variable of the same name is defined in two different functions, it counts as 2.)  Extractor tries to be careful about counting variables uniquely, but this part is a bit difficult to do and there are probably situations in which it will miscount things, so caveats apply.

* _List of functions called_. A list of tuples consisting of "uncommon" functions called anywhere in the file, and the number of times the calls are found.  _Uncommon_ means that certain built-in and common functions in Python are ignored.  The lists of ignored names can be found near the top of the file [file_parser.py](file_parser.py).

With respect to names of functions, classes and variables: The system ignores names (variables, functions, etc.) that are less than 3 characters long, and those that are common Python function names, built-in functions, and various commonly-used Python functions like `join` and `append`.

To illustrate, suppose that we have the following very simple Python file:

    #!/usr/bin/env python
    # This is a header comment.
    
    import foo
    import floop
    
    # This is a comment after the first line of code.
    
    class SomeClass():
        '''Some class doc.'''

        def __init__(self):
            pass
    
        def some_function_on_class():
            '''Some function doc.'''
            some_variable = 1
            some_variable = foo.func()
    
    if __name__ == '__main__':
        bar = SomeClass()
        print(bar.some_function_on_class())

Then, the dictionary returned by Extractor for this file will look like this:

    {'name': 'test.py',
     'type': 'file',
     'code_language': 'Python',
     'text_language': 'en',
     'body':
      {'header': 'This is a header comment.'
       'comments': ['This is a comment after the first line of code.'],
       'docstrings': ['Some class doc.', 'Some function doc.'],
       'strings': [('__main__', 1)],
       'imports': [('foo', 1), ('floop', 1)],
       'classes': [('SomeClass', 1)],
       'functions': [('SomeClass.some_function_on_class', 1)],
       'variables': [('bar', 1), ('some_variable', 1)],
       'calls': [('foo.func', 1), ('SomeClass', 1),
                 ('bar.some_function_on_class', 1)],
       },
    }

The dictionary of elements can have empty values for the various keys even when a file contains code that we parse (currently, Python).  This can happen if the file is empty or something goes badly wrong during parsing such as encountering a syntactic error in the code.  (The latter happens because the process parses code into an AST to extract the elements, and this can fail if the code is unparseable.)

☕ More information about text processing performed
--------------------------------------------------

There are two text processing situations that Extractor encounters: non-code files that contain text, and code (currently, Python) files.  In both cases, Extractor cleans up and processes the text to a limited extent in order to try to make it more easily processed by subsequent natural language procedures.

For non-code files, if the file is not literally plain text, Extractor first extracts the text from it.  It currently converts the following formats: HTML, Markdown, AsciiDoc, reStructuredText, RTF, and Textile.  Its approach always begins by converting these formats to HTML, and then it post-processes the results.  The post-processing performed is to add periods at the ends of titles, paragraphs, list items, and table cells, if periods are missing, to make the result appear more like normal English sentences.  (This makes it easier for a sentence segmentation function to take the result and parse the text into sentences.)  Extractor also removes `<pre>` and `<img>` elements completely.

For code files, the text that appears in (1) the header section, (2) doc strings, (3) comments and (4) other strings, is extracted individually as described in a separate section above.  Extractor performs some additional post-processing on the text, again mostly aimed at turning fragments of text into sentences based on heuristics, but also including some miscellaneous cleanup operations like removing non-alphanumeric characters that are not part of identifiers.

⁇ Getting help and support
--------------------------

If you find an issue, please submit it in [the GitHub issue tracker](https://github.com/casics/extractor/issues) for this repository.

♬ Contributing &mdash; info for developers
------------------------------------------

A lot remains to be done on CASICS in many areas.  We would be happy to receive your help and participation if you are interested.  Please feel free to contact the developers either via GitHub or the mailing list [casics-team@googlegroups.com](casics-team@googlegroups.com).

Everyone is asked to read and respect the [code of conduct](CONDUCT.md) when participating in this project.

❤️ Acknowledgments
------------------

Funding for this and other CASICS work has come from the [National Science Foundation](https://nsf.gov) via grant NSF EAGER #1533792 (Principal Investigator: Michael Hucka).
    
<br>
<div align="center">
  <a href="https://www.nsf.gov">
    <img width="105" height="105" src=".graphics/NSF.svg">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://www.caltech.edu">
    <img width="100" height="100" src=".graphics/caltech-round.svg">
  </a>
</div>
