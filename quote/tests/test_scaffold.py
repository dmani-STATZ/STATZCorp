"""
Scaffold-level guarantees for the quote app.

These lock in the wiring contracts that fail silently rather than loudly:
the URL namespace (permission middleware resolves it), the read-only rule
toward dibbs, and the auto-award remarks gate.
"""
from decimal import Decimal

from django.apps import apps
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from quote.models import QuoteBid, QuoteEmail, QuoteRFQ, QuoteSupplierQuote


class QuoteWiringTests(SimpleTestCase):
    def test_app_is_installed_with_expected_label(self):
        config = apps.get_app_config('quote')
        self.assertEqual(config.name, 'quote')
        self.assertEqual(config.label, 'quote')

    def test_namespace_resolves(self):
        # LoginRequiredMiddleware maps this namespace onto users.AppRegistry.
        # If the namespace changes, permission gating silently no-ops.
        self.assertEqual(reverse('quote:dashboard'), '/quote/')

    def test_every_model_sets_an_explicit_quote_prefixed_table(self):
        for model in apps.get_app_config('quote').get_models():
            table = model._meta.db_table
            self.assertTrue(
                table.startswith('quote_'),
                f'{model.__name__} has db_table={table!r}; expected a quote_ prefix',
            )
            self.assertNotEqual(
                table, model._meta.app_label + '_' + model.__name__.lower(),
                f'{model.__name__} looks auto-named; set db_table explicitly',
            )


class ReadOnlyTowardDibbsTests(SimpleTestCase):
    """
    The quote app references dibbs/suppliers/products but must never own or
    alter their schema. Catching a stray FK onto an app it should not know
    about is the point here.
    """

    def test_foreign_keys_into_other_apps_do_not_own_the_target(self):
        for model in apps.get_app_config('quote').get_models():
            for field in model._meta.get_fields():
                if not getattr(field, 'many_to_one', False) and not getattr(field, 'one_to_one', False):
                    continue
                if not hasattr(field, 'related_model') or field.related_model is None:
                    continue
                target_label = field.related_model._meta.app_label
                if target_label == 'quote':
                    continue
                self.assertIn(
                    target_label,
                    {'dibbs', 'suppliers', 'products', 'auth', 'contracts'},
                    f'{model.__name__}.{field.name} points at unexpected app {target_label}',
                )


class LandedCostTests(SimpleTestCase):
    def test_landed_unit_cost_sums_adders_in_decimal(self):
        quote = QuoteSupplierQuote(
            supplier_unit_cost=Decimal('32.50000'),
            packaging_adder_unit=Decimal('0.60000'),
            freight_adder_unit=Decimal('0.40000'),
            lead_time_days=45,
        )
        total = quote.landed_unit_cost

        self.assertEqual(total, Decimal('33.50000'))
        self.assertIsInstance(total, Decimal)

    def test_landed_unit_cost_treats_missing_adders_as_zero(self):
        quote = QuoteSupplierQuote(
            supplier_unit_cost=Decimal('10'),
            packaging_adder_unit=None,
            freight_adder_unit=None,
            lead_time_days=30,
        )
        self.assertEqual(quote.landed_unit_cost, Decimal('10'))


class AutoAwardGateTests(TestCase):
    """
    Character 9 of the solicitation number being T or U means the solicitation
    is auto-award eligible, and BQ col 121 must then stay empty.
    """

    def _bid_for(self, sol_number):
        from dibbs.models import Solicitation, SolicitationLine

        sol = Solicitation.objects.create(solicitation_number=sol_number)
        line = SolicitationLine.objects.create(solicitation=sol, nsn='8465016131241')
        return QuoteBid(
            line=line,
            quoter_cage='1PN61',
            quote_for_cage='1PN61',
            unit_price=Decimal('34.45000'),
            delivery_days=45,
            manufacturer_dealer='DD',
        )

    def test_t_in_position_nine_is_auto_award(self):
        # SPE4A626T36QG -> index 8 is 'T'
        self.assertTrue(self._bid_for('SPE4A626T36QG').is_auto_award_solicitation)

    def test_u_in_position_nine_is_auto_award(self):
        self.assertTrue(self._bid_for('SPE4A626U36QG').is_auto_award_solicitation)

    def test_q_in_position_nine_is_not_auto_award(self):
        # SPE1C126Q0528 -> index 8 is 'Q'
        self.assertFalse(self._bid_for('SPE1C126Q0528').is_auto_award_solicitation)

    def test_short_solicitation_number_is_not_auto_award(self):
        self.assertFalse(self._bid_for('SPE1C126').is_auto_award_solicitation)


class EmailClaimTests(TestCase):
    def test_claim_is_not_held_by_other_when_unclaimed(self):
        from django.contrib.auth.models import User
        from django.utils import timezone

        user = User.objects.create_user('rep1')
        email = QuoteEmail.objects.create(
            graph_message_id='AAA',
            sender_email='sales@vortextactical.com',
            received_at=timezone.now(),
        )
        self.assertFalse(email.is_claimed_by_other(user))

    def test_claim_blocks_a_second_rep_then_releases_on_reclaim(self):
        from django.contrib.auth.models import User
        from django.utils import timezone

        rep1 = User.objects.create_user('rep1')
        rep2 = User.objects.create_user('rep2')
        first = QuoteEmail.objects.create(
            graph_message_id='AAA',
            sender_email='a@example.com',
            received_at=timezone.now(),
        )
        second = QuoteEmail.objects.create(
            graph_message_id='BBB',
            sender_email='b@example.com',
            received_at=timezone.now(),
        )

        first.claim_for(rep1)
        self.assertTrue(first.is_claimed_by_other(rep2))
        self.assertFalse(first.is_claimed_by_other(rep1))

        # Claiming a second message releases the first -- one open email per rep.
        second.claim_for(rep1)
        first.refresh_from_db()
        self.assertIsNone(first.claimed_by_id)
        self.assertIsNone(first.claim_expires_at)


class QuoteRFQConstraintTests(TestCase):
    def test_one_rfq_per_line_and_supplier(self):
        from django.db import IntegrityError, transaction
        from dibbs.models import Solicitation, SolicitationLine
        from suppliers.models import Supplier

        sol = Solicitation.objects.create(solicitation_number='SPE1C126Q0528')
        line = SolicitationLine.objects.create(solicitation=sol, nsn='8465016131241')
        supplier = Supplier.objects.create(name='Vortex Tactical', cage_code='0SKY9')

        QuoteRFQ.objects.create(line=line, supplier=supplier)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                QuoteRFQ.objects.create(line=line, supplier=supplier)


class DashboardRenderTests(TestCase):
    """The shell must actually render -- a missing block or bad {% url %} is a 500."""

    def setUp(self):
        from django.contrib.auth.models import User
        from users.models import AppPermission, AppRegistry

        self.user = User.objects.create_user('rep1', password='pw-for-test-only')
        self.no_access_user = User.objects.create_user('rep_no_access')

        # The quote app is registered in users.AppRegistry by migration 0002,
        # which makes it deny-by-default. A rep needs an explicit grant.
        quote_app = AppRegistry.objects.get(app_name='quote')
        AppPermission.objects.create(
            user=self.user, app_name=quote_app, has_access=True,
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('quote:dashboard'))
        self.assertIn(response.status_code, (302, 403))

    def test_logged_in_user_without_app_permission_is_denied(self):
        # Deny-by-default is the whole point of the AppRegistry row. If this
        # ever passes with a 200, the app has silently gone fail-open.
        self.client.force_login(self.no_access_user)
        response = self.client.get(reverse('quote:dashboard'))

        self.assertNotEqual(response.status_code, 200)

    def test_dashboard_renders_for_logged_in_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('quote:dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'quote/dashboard.html')
        self.assertTemplateUsed(response, 'quote/base.html')
        self.assertTemplateUsed(response, 'base_template.html')

    def test_dashboard_body_actually_has_content(self):
        # Extending base_template.html without defining {% block body %} yields
        # a page that renders 200 but is visually empty. Assert the real text.
        self.client.force_login(self.user)
        html = self.client.get(reverse('quote:dashboard')).content.decode()

        self.assertIn('app-shell', html)
        self.assertIn('DIBBS quoting workspace', html)

    def test_quote_templates_add_no_cdn_tags(self):
        # GCC High CSP: quote pages must not pull external assets.
        import pathlib
        for path in pathlib.Path('quote/templates').rglob('*.html'):
            source = path.read_text(encoding='utf-8')
            for host in ('cdn.jsdelivr.net', 'code.jquery.com', 'unpkg.com',
                         'cdnjs.cloudflare.com'):
                self.assertNotIn(
                    host, source,
                    f'{path} references CDN host {host}; quote templates must be local-only',
                )

    def test_quote_templates_use_no_tailwind_utility_soup(self):
        import pathlib
        for path in pathlib.Path('quote/templates').rglob('*.html'):
            source = path.read_text(encoding='utf-8')
            self.assertNotIn('hover:', source, f'{path} contains Tailwind-style classes')
