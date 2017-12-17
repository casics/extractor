# =============================================================================
# @file   Makefile
# @brief  Makefile for CASICS Extractor
# @author mhucka@caltech.edu
# @license Please see the file named LICENSE in the project directory
# @website https://github.com/casics/spiral
# =============================================================================

# The approach here is designed to create only one tags file, in the current
# directory, by recursively looking in subdirectories for source files to use
# as input.  Tell Emacs to use that TAGS file by using M-x visit-tags-table.

tags etags: etags-version-check TAGS

etags-command ?= etags $(ETAGSFLAGS)

files-to-tag := $(shell find . -name '*.py' -o -name '*.java')

TAGS: $(files-to-tag)
	$(etags-command) $(files-to-tag)

etags-version-check: 
	@if test -z "`etags --version 2>&1 | grep 'Free Software'`"; then \
	  echo "Your 'etags' command is not the GNU version, and I'm"; \
	  echo "afraid I don't know how to work with it. Quitting."; \
	  exit 2; \
	fi
