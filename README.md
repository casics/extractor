Elementizer
===========

This provides a network server (_Elementizer_) that is meant to run on the repository server.  Given a repository id, it returns a JSON data structure containing a highly processed and condensed version of the directory contents of that repository.  The network communication protocol is implemented using Pyro4, a very easy-to-use Python RPC library.

The format of the data
----------------------

The format of the JSON structure is simple and recursive.  Each element is three-item dictionary: the key `'name'` having as its associated value the name of a file or directory, the key `'type'` having as its value either `'dir'` or `'file'`, and the key `'body'` containing the contents of the file or directory.

* If an item is a directory, the three-item dictionary looks like this:

        { 'name': 'the directory name', 'type': 'dir', 'body': [ ... ] }

* If an item is a file, the two-item dictionary looks like this:

        { 'name': 'the file name', 'type': 'file', 'body': content }

In the case of a directory, the value associated with the key `'body'` is a list that can be either empty (`[]`) if the directory is empty, or else a list of dictionaries, each of which the same basic two-element structure.  In the case of a file, the content associated with the key `'body'` can be one of four things: (1) an empty string, if the file is empty; (2) a string containing the plain-text content of the file (if the file is a non-code text file), (3) a dictionary containing the processed and reduced contents of the file (if the file is a code file), or (4) `None`, if the file is something we ignore.  Reasons for ignoring a file include if it is a non-code file larger than 1 MB.

Altogether, this leads to the following possibilities:

* `{'name': 'abc', 'type': 'dir', 'body': []}` if `'name'` is an empty directory
* `{'name': 'abc', 'type': 'dir', 'body': [ ...dicts... ]` if it's not empty
* `{'name': 'abc', 'type': 'file', 'body': ''}` if the file is empty
* `{'name': 'abc', 'type': 'file', 'body': '...string...'}` if the file contains text but not code
* `{'name': 'abc', 'type': 'file', 'body': { elements } }` if the file contains code
* `{'name': 'abc', 'type': 'file', 'body': None}` if the file is ignored

When it comes to non-code text files, if the file is not literally plain text, Elementizer extracts the text from it.  It currently converts the following formats: HTML, Markdown, AsciiDoc, reStructuredText, RTF, and Textile.   It does this by using a variety of utilities such as BeautifulSoup to convert the formats to plain text, and returns this as a single string.  In the case of a code file, the value associated with the `'body'` key is a dictionary of elements described in more detail below.


Interacting with Elementizer on the command line
------------------------------------------------

The API provided by Elementizer consists of a handful of methods on the RPC endpoint.  The file `elementizer.py` implements a simple interactive REPL interface for exploring and testing, although calling programs can interact with the interface interface more directly.  The interactive interface in `elementizer.py` can be started by providing the URI to the server instance, and a cryptographic key:

    ./elementizer.py -k THE_KEY -u THE_URI

The values of `THE_KEY` and `THE_URI` are not stored anywhere and must be communicated separately.  Once the interactive interface starts up (it's just a normal IPython loop), the object `elementizer` is the handle to the RPC interface.  The following are the available methods:

* `elementizer.get_dir_content(ID)` returns the structure discussed above for the repository whose identifier is `ID`.
* `elementizer.get_repo_path(ID)` returns a single string, the repository path, for a repository whose identifier is `ID`.
* `elementizer.get_status()` returns a string with some information about the status of the server


Programming calls to Elementizer
--------------------------------

To call Elementizer from a program, first import the module and then create an object of class `ElementizerClient` with arguments for the URI and the crypto key (in that order).  After that, the same methods above will be available on the object.  Example:

    from elementizer import ElementizerClient

    elementizer = ElementizerClient(uri, key)
    print(elementizer.get_status())


More information about the parsed file contents
-----------------------------------------------

The file parser attempts to reduce code files to "essentials" by throwing away most things and segregating different types of elements.  The elements in the dictionary are as follows:

* _Header text_. This is the text of the header up to the first line of code in the file, minus leading comment character and blank lines.

* _List of imports_. A list of the names of all Python libraries imported using either `import` or `from`.

* _List of comments_.  A list of all comment lines in the file, minus leading comment characters, blank lines, and lines of comments that don't
contain any alphanumeric characters.  (So, things like line of dashes are skipped.)

* _List of strings_.  A list of all strings longer than 6 characters.

* _List of class names defined in the file_. A list of the classes defined in the file.

* _List of function names defined in the file_.  A list of the functions defined in the file, whether the functions are associated with classes or are standalone functions.

* _List of variable names defined in the file_.  A list of variables defined in the file.

* _List of functions called_. A list of "uncommon" functions called anywhere in the file.

With respect to names of functions, classes and variables: The system ignores names (variables, functions, etc.) that are less than 3 characters long, and those that are common Python function names, built-in functions, and various commonly-used Python functions like `join` and `append`.

To illustrate, suppose that we have the following very simple Python file:

    # This is a header comments
    
    import foo
    import floop
    
    # This is a comment after the first line of code.
    
    class SomeClass():
        def __init__(self):
            pass
    
        def some_function_on_class():
            some_variable = 1
            some_variable = foo.func()
    
    if __name__ == '__main__':
        bar = SomeClass()
        print(bar.some_function_on_class())

Then, the dictionary returned by Elementizer for this file will look like this:

    { 'header': 'This is a header comments\n\n\n\n\n',
      'imports': ['foo'],
      'comments': ['This is a comment after the first line of code.'],
      'strings': ['__main__'],
      'classes': ['SomeClass'],
      'functions': ['some_function_on_class'],
      'variables': ['some_variable', 'bar'],
      'calls': ['foo.func', 'SomeClass', 'bar.some_function_on_class'] }
