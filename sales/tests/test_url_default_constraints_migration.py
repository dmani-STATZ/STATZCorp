"""Phase C URL default-constraint migration is a no-op on SQLite."""

import importlib
from unittest.mock import MagicMock

from django.db import connection
from django.test import SimpleTestCase

_mod = importlib.import_module(
    "sales.migrations.0063_dibbs_award_url_default_constraints"
)


class UrlDefaultConstraintsMigrationTests(SimpleTestCase):
    def test_0063_forwards_and_backwards_noop_when_not_microsoft(self):
        self.assertNotEqual(connection.vendor, "microsoft")

        schema_editor = MagicMock()
        schema_editor.connection.vendor = connection.vendor

        class _Apps:
            pass

        # Vendor guard returns immediately — no DB writes on SQLite/CI.
        _mod._add_url_defaults(_Apps(), schema_editor)
        _mod._drop_url_defaults(_Apps(), schema_editor)
        schema_editor.connection.cursor.assert_not_called()
