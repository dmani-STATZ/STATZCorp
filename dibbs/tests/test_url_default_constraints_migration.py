"""The SQL Server URL default-constraint helpers are a no-op on SQLite."""

from unittest.mock import MagicMock

from django.db import connection
from django.test import SimpleTestCase

from dibbs import db_objects


class UrlDefaultConstraintsTests(SimpleTestCase):
    def test_forwards_and_backwards_noop_when_not_microsoft(self):
        self.assertNotEqual(connection.vendor, "microsoft")

        schema_editor = MagicMock()
        schema_editor.connection.vendor = connection.vendor

        class _Apps:
            pass

        # Vendor guard returns immediately — no DB writes on SQLite/CI.
        db_objects.add_url_defaults(_Apps(), schema_editor)
        db_objects.drop_url_defaults(_Apps(), schema_editor)
        schema_editor.connection.cursor.assert_not_called()
