"""Unit tests for build_explorer_uri() in contracts.services.sharepoint_paths."""
from django.test import SimpleTestCase, override_settings

from contracts.services.sharepoint_paths import build_explorer_uri

_EXPLORER_SETTINGS = {
    "EXPLORER_SHAREPOINT_STRIP_PREFIX": "Statz-Public/data/V87",
    "EXPLORER_LOCAL_MOUNT": "OneDrive - statzcorpgcch/Statz - V87",
}


@override_settings(**_EXPLORER_SETTINGS)
class BuildExplorerUriTests(SimpleTestCase):
    def test_regular_contract_folder(self):
        path = "Statz-Public/data/V87/aFed-DOD/Contract SPE3SE-26-V-0530/"
        expected = (
            "statzfile:///OneDrive%20-%20statzcorpgcch/Statz%20-%20V87/"
            "aFed-DOD/Contract%20SPE3SE-26-V-0530"
        )
        self.assertEqual(build_explorer_uri(path), expected)

    def test_delivery_order_folder(self):
        path = (
            "Statz-Public/data/V87/aFed-DOD/Contract SPE3SE-26-V-0530/"
            "Delivery Order SPE7L0-26-F-3034/"
        )
        expected = (
            "statzfile:///OneDrive%20-%20statzcorpgcch/Statz%20-%20V87/"
            "aFed-DOD/Contract%20SPE3SE-26-V-0530/"
            "Delivery%20Order%20SPE7L0-26-F-3034"
        )
        self.assertEqual(build_explorer_uri(path), expected)

    def test_closed_contract_folder(self):
        path = (
            "Statz-Public/data/V87/aFed-DOD/Closed Contracts/"
            "Contract SPE3SE-26-V-0530/"
        )
        expected = (
            "statzfile:///OneDrive%20-%20statzcorpgcch/Statz%20-%20V87/"
            "aFed-DOD/Closed%20Contracts/Contract%20SPE3SE-26-V-0530"
        )
        self.assertEqual(build_explorer_uri(path), expected)

    def test_legacy_unc_path_returns_empty(self):
        path = r"\\STATZFS01\public\CJ_Data\data\V87\aFed-DOD\Contract X"
        self.assertEqual(build_explorer_uri(path), "")

    def test_sharepoint_url_returns_empty(self):
        path = "https://statzcorpgcch.sharepoint.us/sites/Statz/Shared%20Documents/foo"
        self.assertEqual(build_explorer_uri(path), "")

    def test_empty_and_none_return_empty(self):
        self.assertEqual(build_explorer_uri(""), "")
        self.assertEqual(build_explorer_uri(None), "")
