from django import forms
from django.contrib.admin.widgets import AdminTextareaWidget

class MarkupTextarea(forms.widgets.Textarea):
    def render(self, name, value, attrs=None):
        if value is not None:
            try:
                value = value.raw
            except AttributeError:
                pass
        return super(MarkupTextarea, self).render(name, value, attrs)

class AdminMarkupTextareaWidget(MarkupTextarea, AdminTextareaWidget):
    pass
