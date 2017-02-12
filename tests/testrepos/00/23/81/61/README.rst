==================
django-markupfield
==================

A custom fork of James Turk's implementation of a MarkupField for Django.  A
MarkupField is a TextField that automatically renders and stores both its
raw and rendered values in the database, on the assumption that disk space
is cheaper than CPU cycles in a web application.

Installation
============

You can obtain this fork of django-markupfield by checking out the `latest
source <http://github.com/carljm/django-markupfield>`_.  The original
version is available on `PyPI
<http://pypi.python.org/pypi/django-markupfield>`_ or `GitHub
<http://github.com/jamesturk/django-markupfield>`_.

To install a source distribution::

    python setup.py install

It is also possible to install django-markupfield with
`pip <http://pypi.python.org/pypi/pip>`_ or easy_install.

It is not necessary to add ``'markupfield'`` to your
``INSTALLED_APPS``, it merely needs to be on your ``PYTHONPATH``.

Settings
========

To make use of MarkupField you should define the ``MARKUP_FILTER``
setting.  ``MARKUP_FILTER`` should be a two-tuple where the first
element is a Python dotted path to a markup filter function.  This
function should accept markup as its first argument and return HTML.
It may accept other keyword arguments as well.  You may parse your
markup using any method you choose, as long as you can wrap it in a
function that meets these criteria.

The second element must be a dictionary of keyword arguments to pass
to the filter function.  The dictionary may be empty.

For example, if you have python-markdown installed, you could use it
like this::

    MARKUP_FILTER = ('markdown.markdown', {'safe_mode': True})

Alternatively, you could use the "textile" filter provided by Django
like this::

    MARKUP_FILTER = ('django.contrib.markup.templatetags.markup.textile', {})

(The textile filter function doesn't accept keyword arguments, so the
kwargs dictionary must be empty in this case.)

``django-markupfield`` provides one sample rendering function,
``render_rest`` in the ``markupfield.renderers`` module.

Usage
=====

MarkupField is easy to add to any model definition::

    from django.db import models
    from markupfield.fields import MarkupField

    class Article(models.Model):
        title = models.CharField(max_length=100)
        body = MarkupField()

``MarkupField`` automatically creates an extra non-editable field
``_body_rendered`` to store the rendered markup. This field doesn't need to
be accessed directly; see below.

Accessing a MarkupField on a model
----------------------------------

When accessing an attribute of a model that was declared as a
``MarkupField``, a ``Markup`` object is returned.  The ``Markup`` object has
two attributes:

``raw``:
    The unrendered markup.
``rendered``:
    The rendered HTML version of ``raw`` (read-only).

This object also has a ``__unicode__`` method that calls
``django.utils.safestring.mark_safe`` on ``rendered``, allowing
``MarkupField`` attributes to appear in templates as rendered HTML without
any special template tag or having to access ``rendered`` directly.

Assuming the ``Article`` model above::

    >>> a = Article.objects.all()[0]
    >>> a.body.raw
    u'*fancy*'
    >>> a.body.rendered
    u'<p><em>fancy</em></p>'
    >>> print unicode(a.body)
    <p><em>fancy</em></p>

Assignment to ``a.body`` is equivalent to assignment to ``a.body.raw``.

.. note::
    a.body.rendered is only updated when a.save() is called

Editing a MarkupField in a form
-------------------------------

When editing a ``MarkupField`` model attribute in a ``ModelForm`` (i.e. in
the Django admin), you'll generally want to edit the original markup and not
the rendered HTML.  Because the ``Markup`` object returns rendered HTML from
its __unicode__ method, it's necessary to use the ``MarkupTextarea`` widget
from the ``markupfield.widgets`` module, which knows to return the raw
markup instead.  There is also an ``AdminMarkupTextareaWidget`` for use in
the admin.

These widgets are normally used automatically, so no intervention is
required (i.e. the ``formfield`` method of ``MarkupField`` returns a form
field with the ``MarkupTextarea`` widget, and likewise the admin's default
formfields dictionary is modified to use ``AdminMarkupTextareaWidget`` for
``MarkupField``). But if you apply your own custom widget to the form field
representing a ``MarkupField``, your widget must either inherit from
``MarkupTextarea`` or its ``render`` method must convert its ``value``
argument to ``value.raw``.

Todo
====

 * add a save_markup() method which accepts a rendering function and kwargs

Origin
======

The following paragraphs are James Turk's description of the original
purpose of this project. My fork is intended to modify the project to meet
the description put forward by James Bennett and others in `this django-dev
thread <http://groups.google.com/group/django-developers/browse_thread/thread/c9124d565c17f972>`_.

    Jacob Kaplan-Moss commented on twitter that he'd possibly like to
    see a MarkupField in core and I filed a ticket on the Django trac
    http://code.djangoproject.com/ticket/10317

    The resulting django-dev discussion drastically changed the
    purpose of the field.  While I initially intended to write a
    version that seemed more acceptable for Django core I wound up
    feeling that the 'acceptable' version had so little functionality
    and so much complexity it wasn't worth using.
