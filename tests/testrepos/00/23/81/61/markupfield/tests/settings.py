DATABASE_ENGINE = 'sqlite3'
DATABASE_NAME = 'markuptest.db'

MARKUP_FILTER = ('markdown.markdown', {'safe_mode': True})

INSTALLED_APPS = (
    'markupfield.tests',
)
