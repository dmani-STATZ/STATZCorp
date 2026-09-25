"""
DEV ONLY -- seed demonstration data for the quoting workflow.

    python manage.py seed_quote_demo          # clear any prior demo data, then seed
    python manage.py seed_quote_demo --clear  # remove demo data, seed nothing
    python manage.py seed_quote_demo --list   # show what is currently seeded

This is a management command, NOT a data migration, specifically so it can
never run as part of a deploy. It additionally refuses to run when it detects a
production environment. See the guard in `_assert_not_production`.

=== How demo rows stay separable from real data ===

The dev database is a production-like copy (hundreds of thousands of real
solicitations and awards), so every row this command creates is tagged, and
--clear only ever deletes tagged rows:

  * sales.Solicitation   -> linked to an ImportBatch whose imported_by is
                            DEMO_IMPORTED_BY. Deleting that batch's
                            solicitations cascades to lines, RFQs, quotes,
                            bids, outcomes and email links.
  * sales.DibbsAward     -> notice_id starts with DEMO_NOTICE_PREFIX.
  * suppliers.Supplier   -> notes contains DEMO_MARKER.
  * quote.QuoteEmail     -> graph_message_id starts with DEMO_GRAPH_PREFIX.

Nothing is matched by solicitation number, CAGE or name alone, so a real row
that happens to share an identifier is never touched.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from products.models import Nsn
from sales.models import (
    ApprovedSource,
    DibbsAward,
    ImportBatch,
    Solicitation,
    SolicitationLine,
    SupplierFSC,
    SupplierNSN,
)
from suppliers.models import Supplier, SupplierType

from quote.models import (
    BidOutcome,
    QuoteBid,
    QuoteEmail,
    QuoteEmailAttachment,
    QuoteEmailSolLink,
    QuoteRFQ,
    QuoteSupplierQuote,
)

# ── Tags that make demo rows identifiable and safely deletable ───────────────
DEMO_MARKER = '[SEED_QUOTE_DEMO]'
DEMO_IMPORTED_BY = 'seed_quote_demo'
DEMO_NOTICE_PREFIX = 'DEMO-SEED-'
DEMO_GRAPH_PREFIX = 'DEMO-SEED-MSG-'

STATZ_CAGE = '3WGD1'

# ── Suppliers ────────────────────────────────────────────────────────────────
# (name, cage, type_code, is_packhouse)
DEMO_SUPPLIERS = [
    ('Vortex Tactical',           '0SKY9', 'M', False),
    ('Precision Aero',            'D2689', 'M', False),
    ('Apex Fasteners',            '72914', 'D', False),
    ('MedTech Logistics',         '4M773', 'D', False),
    ('All-Seals Inc',             '1ALL7', 'M', False),
    ('Commercial Kitchen Direct', '7CKD3', 'D', False),
    ('Titan Defense Systems',     '8FRT2', 'D', False),
    ('PackCo Mil-Spec',           '9PACK', 'P', True),
]


def _d(value):
    return Decimal(str(value))


class Command(BaseCommand):
    help = 'DEV ONLY. Seed sample quoting data covering every workflow stage.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear', action='store_true',
            help='Remove all demo data and seed nothing.',
        )
        parser.add_argument(
            '--list', action='store_true',
            help='Report what demo data currently exists, change nothing.',
        )

    # ── Guards ───────────────────────────────────────────────────────────────

    def _assert_not_production(self):
        """
        Refuse to touch a production database. Two independent signals, because
        this command creates fake solicitations, awards and suppliers that would
        be very unpleasant to find in the live ERP.
        """
        import os

        reasons = []
        if getattr(settings, 'IS_PRODUCTION', False):
            reasons.append('settings.IS_PRODUCTION is True')
        if os.environ.get('WEBSITE_SITE_NAME'):
            reasons.append(
                f"WEBSITE_SITE_NAME is set ({os.environ['WEBSITE_SITE_NAME']!r})"
            )

        if reasons:
            raise CommandError(
                'seed_quote_demo refuses to run against production: '
                + '; '.join(reasons)
                + '. This command creates fake solicitations, awards and '
                  'suppliers and must never run outside dev.'
            )

    # ── Entry point ──────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        self._assert_not_production()

        if options['list']:
            self._report()
            return

        removed = self._clear()
        self.stdout.write(f'Removed {removed} existing demo row(s).')

        if options['clear']:
            self.stdout.write(self.style.SUCCESS('Demo data cleared.'))
            return

        with transaction.atomic():
            self._seed()

        self._report()
        self.stdout.write(self.style.SUCCESS(
            '\nSeeded. Sign in and open /quote/ to see it.'
        ))

    # ── Clear ────────────────────────────────────────────────────────────────

    def _clear(self):
        """Delete only tagged rows. Returns the number of rows removed."""
        total = 0

        # Emails first: their sol links cascade, but the emails themselves are
        # tagged separately from the solicitations.
        total += QuoteEmail.objects.filter(
            graph_message_id__startswith=DEMO_GRAPH_PREFIX
        ).delete()[0]

        # Solicitations tagged via their import batch. Cascades through lines
        # to RFQs, quotes, bids and outcomes.
        demo_batches = list(
            ImportBatch.objects.filter(imported_by=DEMO_IMPORTED_BY)
            .values_list('id', flat=True)
        )
        if demo_batches:
            total += Solicitation.objects.filter(
                import_batch_id__in=demo_batches
            ).delete()[0]
            total += ApprovedSource.objects.filter(
                import_batch_id__in=demo_batches
            ).delete()[0]
            total += ImportBatch.objects.filter(id__in=demo_batches).delete()[0]

        total += DibbsAward.objects.filter(
            notice_id__startswith=DEMO_NOTICE_PREFIX
        ).delete()[0]

        # Only NSN rows this command created carry the marker; real product
        # records are never stamped, so they can never be deleted here.
        total += Nsn.objects.filter(
            dimension_source_notes__contains=DEMO_MARKER
        ).delete()[0]

        # Suppliers last -- capability rows cascade off them.
        total += Supplier.objects.filter(notes__contains=DEMO_MARKER).delete()[0]

        return total

    # ── Report ───────────────────────────────────────────────────────────────

    def _report(self):
        batches = ImportBatch.objects.filter(imported_by=DEMO_IMPORTED_BY)
        sols = Solicitation.objects.filter(import_batch__in=batches)

        self.stdout.write('\nDemo data currently present:')
        rows = [
            ('suppliers', Supplier.objects.filter(notes__contains=DEMO_MARKER).count()),
            ('solicitations', sols.count()),
            ('solicitation lines', SolicitationLine.objects.filter(solicitation__in=sols).count()),
            ('RFQs', QuoteRFQ.objects.filter(line__solicitation__in=sols).count()),
            ('supplier quotes', QuoteSupplierQuote.objects.filter(line__solicitation__in=sols).count()),
            ('bids', QuoteBid.objects.filter(solicitation__in=sols).count()),
            ('bid outcomes', BidOutcome.objects.filter(bid__solicitation__in=sols).count()),
            ('emails', QuoteEmail.objects.filter(graph_message_id__startswith=DEMO_GRAPH_PREFIX).count()),
            ('awards', DibbsAward.objects.filter(notice_id__startswith=DEMO_NOTICE_PREFIX).count()),
            ('NSN spec rows', Nsn.objects.filter(
                dimension_source_notes__contains=DEMO_MARKER).count()),
        ]
        for label, count in rows:
            self.stdout.write(f'  {label:22} {count}')

        if sols.exists():
            self.stdout.write('\nStages represented:')
            for sol in sols.order_by('solicitation_number'):
                self.stdout.write(
                    f'  {sol.solicitation_number}  {sol.status:14} '
                    f'{(sol.lines.first().nomenclature or ""):22}'
                )

    # ── Seed ─────────────────────────────────────────────────────────────────

    def _seed(self):
        today = timezone.now().date()
        now = timezone.now()

        batch = ImportBatch.objects.create(
            import_date=today - timedelta(days=1),
            imported_at=now,
            in_file_name='in260924.txt',
            bq_file_name='bq260924.txt',
            as_file_name='as260924.txt',
            imported_by=DEMO_IMPORTED_BY,
        )

        suppliers = self._seed_suppliers()
        packhouse = suppliers['9PACK']

        # Each entry drives one solicitation through one stage of the pipeline.
        # Money is internally consistent: final = (base + pack + freight) * (1 + markup).
        specs = [
            # ---- Phase 1: not yet worked -------------------------------------
            dict(
                sol='SPE5EJ26T9021', stage='unmatched',
                nsn='5340-01-234-5678', nom='CLAMP, LOOP', qty=25, uoi='EA',
                due=today + timedelta(days=21),
                set_aside='R', sol_type='T',
            ),
            dict(
                sol='SPE4A126T2948', stage='matched',
                nsn='4810-01-144-4178', nom='GUIDE, DISK, VALVE', qty=5, uoi='EA',
                due=today + timedelta(days=14),
                set_aside='R', sol_type='T',
                match_suppliers=['D2689', '72914'],
                approved_sources=[('D2689', '3851515-101')],
            ),
            # ---- Phase 1: dispatch -------------------------------------------
            dict(
                sol='SPE6V126T4410', stage='rfq_queued',
                nsn='4730-01-111-2222', nom='COUPLING, PIPE', qty=12, uoi='EA',
                due=today + timedelta(days=11),
                set_aside='Y', sol_type='T',
                match_suppliers=['72914', '0SKY9'],
                rfqs=[('72914', QuoteRFQ.STATUS_QUEUED), ('0SKY9', QuoteRFQ.STATUS_QUEUED)],
            ),
            dict(
                sol='SPE8EC26T5533', stage='rfq_sent',
                nsn='5999-01-333-4444', nom='CONTACT, ELECTRICAL', qty=100, uoi='EA',
                due=today + timedelta(days=8),
                set_aside='R', sol_type='T',
                match_suppliers=['1ALL7'],
                rfqs=[('1ALL7', QuoteRFQ.STATUS_SENT)],
            ),
            # ---- Phase 2-4: quoted, bid, awarded -----------------------------
            dict(
                sol='SPE1C126Q0528', stage='won',
                nsn='8465-01-613-1241', nom='CARABINER, PULLEY', qty=2, uoi='EA',
                due=today + timedelta(days=30), submitted=today - timedelta(days=2),
                set_aside='R', sol_type='Q',
                match_suppliers=['0SKY9'],
                approved_sources=[('0SKY9', 'ZPCARA101XX')],
                rfqs=[('0SKY9', QuoteRFQ.STATUS_RESPONDED)],
                quotes=[dict(cage='0SKY9', base='32.50', pack='0.00', freight='0.50',
                             markup='2.00', lead=45, part='ZPCARA101XX',
                             pack_src=QuoteSupplierQuote.PACKAGING_SUPPLIER_INCLUDED,
                             terms='Net 30', selected=True)],
                outcome='WON', award_unit='33.66',
                dims=dict(weight='0.40', l='4.00', w='2.00', h='1.00'),
            ),
            dict(
                sol='SPE4A626T36QG', stage='lost_tight',
                nsn='5305-12-309-7497', nom='SCREW,CAP,HEX HEAD', qty=8, uoi='EA',
                due=today + timedelta(days=7), submitted=today - timedelta(days=3),
                set_aside='N', sol_type='T',
                match_suppliers=['D2689', '72914', '0SKY9'],
                approved_sources=[('D2689', '01104897ES8920-14')],
                rfqs=[('D2689', QuoteRFQ.STATUS_RESPONDED),
                      ('72914', QuoteRFQ.STATUS_RESPONDED),
                      ('0SKY9', QuoteRFQ.STATUS_RESPONDED)],
                # Three competing quotes -> exercises the comparison drawer and
                # the "Auto: Lowest" tally badge.
                quotes=[
                    dict(cage='D2689', base='14.20', pack='0.60', freight='0.40',
                         markup='6.00', lead=30, part='01104897ES8920-14',
                         pack_src=QuoteSupplierQuote.PACKAGING_THIRD_PARTY,
                         packhouse=True, terms='Net 30', selected=True, auto=True),
                    dict(cage='72914', base='15.05', pack='0.60', freight='0.45',
                         markup='6.00', lead=21, part='01104897ES8920-14',
                         pack_src=QuoteSupplierQuote.PACKAGING_THIRD_PARTY,
                         packhouse=True, terms='Net 15', selected=False),
                    dict(cage='0SKY9', base='16.80', pack='0.00', freight='0.55',
                         markup='6.00', lead=60, part='01104897ES8920-14',
                         pack_src=QuoteSupplierQuote.PACKAGING_SUPPLIER_INCLUDED,
                         terms='Net 30', selected=False),
                ],
                outcome='LOST', award_unit='15.50', award_cage='D2689',
                dims=dict(weight='0.10', l='2.00', w='0.50', h='0.50'),
            ),
            dict(
                sol='SPE4A526T476A', stage='lost_wide',
                nsn='5330-01-173-8300', nom='GASKET', qty=2, uoi='EA',
                due=today + timedelta(days=7), submitted=today - timedelta(days=5),
                set_aside='N', sol_type='T',
                match_suppliers=['72914'],
                approved_sources=[('72914', '31-4978-1')],
                rfqs=[('72914', QuoteRFQ.STATUS_RESPONDED)],
                quotes=[dict(cage='72914', base='58.00', pack='0.00', freight='1.50',
                             markup='8.00', lead=20, part='31-4978-1',
                             pack_src=QuoteSupplierQuote.PACKAGING_SUPPLIER_INCLUDED,
                             terms='Net 30', selected=True)],
                outcome='LOST', award_unit='41.20', award_cage='72914',
                dims=dict(weight='0.20', l='6.00', w='6.00', h='0.10'),
            ),
            dict(
                sol='SPE2DH26T7056', stage='lost_tight',
                nsn='6530-01-131-0051', nom='STAND,INTRAVENOUS-IRR', qty=4, uoi='EA',
                due=today + timedelta(days=5), submitted=today - timedelta(days=1),
                set_aside='R', sol_type='T',
                match_suppliers=['4M773'],
                rfqs=[('4M773', QuoteRFQ.STATUS_RESPONDED)],
                quotes=[dict(cage='4M773', base='98.00', pack='0.00', freight='6.50',
                             markup='7.00', lead=35, part='IV-STAND-5C',
                             pack_src=QuoteSupplierQuote.PACKAGING_IN_HOUSE,
                             terms='Net 30', selected=True)],
                outcome='LOST', award_unit='108.50', award_cage='4M773',
                dims=dict(weight='12.00', l='48.00', w='6.00', h='6.00'),
            ),
            dict(
                sol='SPE7L126T16E8', stage='pending',
                nsn='5331-00-303-0091', nom='O-RING', qty=50, uoi='EA',
                due=today + timedelta(days=4), submitted=today - timedelta(days=1),
                set_aside='R', sol_type='T',
                match_suppliers=['1ALL7'],
                rfqs=[('1ALL7', QuoteRFQ.STATUS_RESPONDED)],
                quotes=[dict(cage='1ALL7', base='1.50', pack='0.15', freight='0.05',
                             markup='8.00', lead=25, part='OR-303-0091',
                             pack_src=QuoteSupplierQuote.PACKAGING_IN_HOUSE,
                             terms='Net 30', selected=True)],
                outcome='PENDING',
                dims=dict(weight='0.01', l='1.00', w='1.00', h='0.10'),
            ),
            dict(
                sol='SPE3SE26Q0504', stage='won',
                nsn='7310-GM-502-2323', nom='EQUIPMENT IST - FTRD', qty=1, uoi='EA',
                due=today + timedelta(days=2), submitted=today - timedelta(days=40),
                set_aside='R', sol_type='Q',
                match_suppliers=['7CKD3'],
                rfqs=[('7CKD3', QuoteRFQ.STATUS_RESPONDED)],
                quotes=[dict(cage='7CKD3', base='380.00', pack='0.00', freight='20.00',
                             markup='5.00', lead=90, part='CKD-FTRD-2323',
                             pack_src=QuoteSupplierQuote.PACKAGING_SUPPLIER_INCLUDED,
                             terms='Net 30', selected=True)],
                outcome='WON', award_unit='420.00',
                dims=dict(weight='45.00', l='30.00', w='24.00', h='20.00'),
            ),
        ]

        lines_by_sol = {}
        for spec in specs:
            line = self._seed_solicitation(spec, batch, suppliers, packhouse)
            lines_by_sol[spec['sol']] = line

        self._seed_emails(lines_by_sol, suppliers, now)

    # ── Seed helpers ─────────────────────────────────────────────────────────

    def _seed_suppliers(self):
        types = {t.code: t for t in SupplierType.objects.all()}
        out = {}
        for name, cage, type_code, is_packhouse in DEMO_SUPPLIERS:
            out[cage] = Supplier.objects.create(
                name=name,
                cage_code=cage,
                supplier_type=types.get(type_code),
                is_packhouse=is_packhouse or None,
                business_email=f'sales@{cage.lower()}.example.com',
                notes=f'{DEMO_MARKER} Sample supplier for the quoting demo.',
                archived=False,
            )
        return out

    def _seed_solicitation(self, spec, batch, suppliers, packhouse):
        nsn_plain = spec['nsn'].replace('-', '')

        sol = Solicitation.objects.create(
            solicitation_number=spec['sol'],
            solicitation_type=spec.get('sol_type') or None,
            small_business_set_aside=spec.get('set_aside') or None,
            return_by_date=spec['due'],
            import_date=batch.import_date,
            import_batch=batch,
            status=self._status_for(spec['stage']),
            pdf_file_name=f'{spec["sol"]}.PDF',
            buyer_code='DEMO1',
        )

        line = SolicitationLine.objects.create(
            solicitation=sol,
            line_number='0001',
            purchase_request_number=f'PR{spec["sol"][-8:]}',
            nsn=spec['nsn'],
            fsc=nsn_plain[:4],
            niin=nsn_plain[4:13],
            unit_of_issue=spec['uoi'],
            quantity=spec['qty'],
            delivery_days=60,
            nomenclature=spec['nom'][:21],
            item_type_indicator='1',
            item_description_indicator='P',
            bq_raw_columns=self._bq_template(spec),
        )

        if spec.get('dims'):
            self._seed_nsn_dims(spec)

        for cage, part_number in spec.get('approved_sources', []):
            ApprovedSource.objects.create(
                nsn=nsn_plain,
                approved_cage=cage,
                part_number=part_number,
                company_name=suppliers[cage].name,
                import_batch=batch,
            )

        for cage in spec.get('match_suppliers', []):
            SupplierNSN.objects.get_or_create(
                supplier=suppliers[cage], nsn=nsn_plain,
                defaults={'notes': f'{DEMO_MARKER} demo capability'},
            )
            SupplierFSC.objects.get_or_create(
                supplier=suppliers[cage], fsc_code=nsn_plain[:4],
                defaults={'notes': f'{DEMO_MARKER} demo capability'},
            )

        rfq_by_cage = {}
        for cage, status in spec.get('rfqs', []):
            rfq = QuoteRFQ.objects.create(
                line=line,
                supplier=suppliers[cage],
                status=status,
                email_sent_to=suppliers[cage].business_email,
                sent_at=(timezone.now() - timedelta(days=4))
                if status != QuoteRFQ.STATUS_QUEUED else None,
                response_received_at=(timezone.now() - timedelta(days=2))
                if status == QuoteRFQ.STATUS_RESPONDED else None,
            )
            rfq_by_cage[cage] = rfq

        quotes = []
        for q in spec.get('quotes', []):
            quotes.append(
                self._seed_quote(q, line, spec, suppliers, packhouse, rfq_by_cage)
            )

        if spec.get('outcome'):
            self._seed_bid_and_outcome(spec, sol, line, quotes, suppliers)

        return line

    def _seed_nsn_dims(self, spec):
        """
        Give the NSN physical specs so the freight sub-modal has something to
        prefill.

        Only ever CREATES a row. A pre-existing contracts_nsn record is real
        product data shared with contracts/processing -- overwriting its
        dimensions (and then deleting it on --clear) would destroy real data,
        so an existing row is left completely untouched.
        """
        if Nsn.objects.filter(nsn_code=spec['nsn']).exists():
            self.stdout.write(
                f'  skipped NSN dims for {spec["nsn"]}: a real contracts_nsn '
                f'row already exists and will not be modified'
            )
            return

        dims = spec['dims']
        Nsn.objects.create(
            nsn_code=spec['nsn'],
            description=spec['nom'],
            unit_weight=_d(dims['weight']),
            unit_length=_d(dims['l']),
            unit_width=_d(dims['w']),
            unit_height=_d(dims['h']),
            dimension_source_notes=(
                f'{DEMO_MARKER} Sourced from vendor spec sheet during quoting.'
            ),
            dimensions_last_verified=timezone.now().date() - timedelta(days=30),
        )

    def _seed_quote(self, q, line, spec, suppliers, packhouse, rfq_by_cage):
        base, pack, freight = _d(q['base']), _d(q['pack']), _d(q['freight'])
        markup = _d(q['markup'])
        landed = base + pack + freight
        final = (landed * (Decimal('1') + markup / Decimal('100'))).quantize(
            Decimal('0.00001')
        )
        qty = spec['qty']

        return QuoteSupplierQuote.objects.create(
            rfq=rfq_by_cage.get(q['cage']),
            line=line,
            supplier=suppliers[q['cage']],
            nsn=spec['nsn'],
            supplier_unit_cost=base,
            lead_time_days=q['lead'],
            min_order_qty=1,
            quantity_available=qty,
            offered_part_number=q['part'],
            offered_cage=q['cage'],
            payment_terms=q['terms'],
            packaging_source=q['pack_src'],
            packaging_vendor=packhouse if q.get('packhouse') else None,
            packaging_total_cost=(pack * qty) if pack else None,
            packaging_adder_unit=pack,
            freight_total_cost=freight * qty,
            freight_adder_unit=freight,
            markup_type=QuoteSupplierQuote.MARKUP_PERCENTAGE,
            markup_value=markup,
            final_government_unit_price=final,
            is_selected_for_bid=q.get('selected', False),
            selected_automatically=q.get('auto', False),
            notes=f'{DEMO_MARKER} Transcribed from supplier reply.',
        )

    def _seed_bid_and_outcome(self, spec, sol, line, quotes, suppliers):
        selected = next((q for q in quotes if q.is_selected_for_bid), None)
        if selected is None:
            return

        our_price = selected.final_government_unit_price
        submitted = spec['submitted']

        bid = QuoteBid.objects.create(
            solicitation=sol,
            line=line,
            selected_quote=selected,
            quoter_cage=STATZ_CAGE,
            quote_for_cage=STATZ_CAGE,
            bid_type_code=QuoteBid.BID_WITHOUT_EXCEPTION,
            payment_terms='1',
            vendor_quote_number=f'Q{spec["sol"][-6:]}',
            unit_price=our_price,
            delivery_days=selected.lead_time_days,
            manufacturer_dealer='DD',
            mfg_source_cage=selected.offered_cage,
            part_number_offered_code='1',
            part_number_offered_cage=selected.offered_cage,
            part_number_offered=selected.offered_part_number,
            margin_pct=selected.markup_value,
            bid_status=QuoteBid.STATUS_SUBMITTED,
            submitted_at=timezone.make_aware(
                timezone.datetime.combine(submitted, timezone.datetime.min.time())
            ),
            exported_bq_file=f'bq{submitted.strftime("%y%m%d")}.txt',
        )

        award = None
        award_unit = None
        if spec['outcome'] in ('WON', 'LOST'):
            award_unit = _d(spec['award_unit'])
            we_won = spec['outcome'] == 'WON'
            award = DibbsAward.objects.create(
                solicitation=sol,
                sol_number=spec['sol'],
                notice_id=f'{DEMO_NOTICE_PREFIX}{spec["sol"]}',
                award_date=submitted + timedelta(days=2),
                awardee_cage=STATZ_CAGE if we_won else spec['award_cage'],
                we_won=we_won,
                source=DibbsAward.SOURCE_DIBBS_FILE,
                award_basic_number=f'{spec["sol"][:6]}-26-P-{spec["sol"][-4:]}',
                total_contract_price=(award_unit * spec['qty']).quantize(Decimal('0.01')),
                nsn=spec['nsn'].replace('-', ''),
                nomenclature=spec['nom'],
                aw_file_date=submitted + timedelta(days=2),
            )

        dollar_delta = pct_spread = None
        within_5 = False
        if award_unit is not None and award_unit > 0:
            dollar_delta = (our_price - award_unit).quantize(Decimal('0.00001'))
            pct_spread = (
                (our_price - award_unit) / award_unit * Decimal('100')
            ).quantize(Decimal('0.0001'))
            within_5 = spec['outcome'] == 'LOST' and Decimal('0') < pct_spread <= Decimal('5')

        winner_name = ''
        if award is not None:
            winner_name = (
                'STATZ CORPORATION' if award.we_won
                else suppliers[spec['award_cage']].name.upper()
            )

        BidOutcome.objects.create(
            bid=bid,
            award=award,
            outcome=spec['outcome'],
            submission_date=submitted,
            our_unit_price=our_price,
            award_total_price=award.total_contract_price if award else None,
            award_quantity=spec['qty'] if award else None,
            award_unit_price=award_unit,
            award_unit_price_is_derived=True,
            winning_cage=(award.awardee_cage if award else ''),
            winning_entity_name=winner_name,
            dollar_delta=dollar_delta,
            pct_spread=pct_spread,
            within_5_pct=within_5,
            snapshot_supplier_name=selected.supplier.name,
            snapshot_supplier_unit_cost=selected.supplier_unit_cost,
            snapshot_packhouse_name=(
                selected.packaging_vendor.name if selected.packaging_vendor else ''
            ),
            snapshot_packaging_adder_unit=selected.packaging_adder_unit,
            snapshot_freight_adder_unit=selected.freight_adder_unit,
            snapshot_weight_lbs=_d(spec['dims']['weight']) if spec.get('dims') else None,
            snapshot_dimensions=(
                '{l}" x {w}" x {h}"'.format(**spec['dims']) if spec.get('dims') else ''
            ),
            snapshot_margin_pct=selected.markup_value,
            snapshot_submitter_name='Dion',
            reconciled_at=timezone.now() if award else None,
        )

    def _seed_emails(self, lines_by_sol, suppliers, now):
        """
        Three inbound shapes the mailbox workspace has to handle:
          1. one email -> one solicitation (auto-detected from the subject)
          2. one email -> two solicitations (consolidated RFQ reply)
          3. an orphan with no detectable solicitation
        Plus one carrying an attachment.
        """
        e1 = QuoteEmail.objects.create(
            graph_message_id=f'{DEMO_GRAPH_PREFIX}0001',
            sender_email='sales@vortextactical.com',
            sender_name='Sarah Jenkins',
            subject='RE: RFQ SPE1C126Q0528 (Carabiners)',
            received_at=now - timedelta(hours=6),
            body_preview='Hi Dion, we can supply the carabiner pulleys under P/N '
                         'ZPCARA101XX at $32.50 each...',
            body_html='<p>Good morning Dion,</p><p>We can supply the requested '
                      'hardware for solicitation SPE1C126Q0528:</p>'
                      '<ul><li>NSN 8465-01-613-1241 (CARABINER, PULLEY)</li>'
                      '<li>Our Part #: ZPCARA101XX (CAGE 0SKY9)</li>'
                      '<li>Price: $32.50 per EA</li><li>Delivery: 45 Days ARO</li>'
                      '<li>Payment Terms: Net 30</li></ul>'
                      '<p>Best,<br>Sarah Jenkins</p>',
            headers_json={'Message-ID': '<demo-0001@vortextactical.com>'},
            raw_payload={'demo': True, 'subject': 'RE: RFQ SPE1C126Q0528 (Carabiners)'},
            is_read=True,
            is_orphan=False,
        )
        QuoteEmailSolLink.objects.create(
            email=e1, line=lines_by_sol['SPE1C126Q0528'], detected_automatically=True,
        )

        e2 = QuoteEmail.objects.create(
            graph_message_id=f'{DEMO_GRAPH_PREFIX}0002',
            sender_email='quotes@apexfasteners.com',
            sender_name='Apex Fasteners Inc',
            subject='Pricing for NSN 5305-12-309-7497 & 5330-01-173-8300',
            received_at=now - timedelta(hours=8),
            body_preview='See attached pricing for the two hardware lines you '
                         'requested yesterday...',
            body_html='<p>Dion,</p><p>Here are line item quotes for your recent '
                      'requirements:</p><p><b>Line 1:</b> NSN 5305-12-309-7497 '
                      '(SCREW, CAP, HEXAGON HEAD) &mdash; $14.20 ea, 30 days</p>'
                      '<p><b>Line 2:</b> NSN 5330-01-173-8300 (GASKET) &mdash; '
                      '$58.00 ea, 20 days</p>'
                      '<p>Shipping is $45.00 flat ground for the whole order.</p>',
            headers_json={'Message-ID': '<demo-0002@apexfasteners.com>'},
            raw_payload={'demo': True},
            is_read=False,
            is_orphan=False,
        )
        # The one-email-covers-many-solicitations case.
        for sol_number in ('SPE4A626T36QG', 'SPE4A526T476A'):
            QuoteEmailSolLink.objects.create(
                email=e2, line=lines_by_sol[sol_number], detected_automatically=True,
            )
        QuoteEmailAttachment.objects.create(
            email=e2,
            graph_attachment_id=f'{DEMO_GRAPH_PREFIX}0002-ATT1',
            original_name='Apex_Quote_8841.pdf',
            content_type='application/pdf',
            file_size=18432,
            content=b'%PDF-1.4 demo placeholder, not a real PDF\n',
            downloaded_at=now - timedelta(hours=7),
        )

        # Orphan: no solicitation detectable from subject or body.
        QuoteEmail.objects.create(
            graph_message_id=f'{DEMO_GRAPH_PREFIX}0003',
            sender_email='bids@titandefense.com',
            sender_name='Titan Defense Systems',
            subject='Quote Ref #TD-8841',
            received_at=now - timedelta(days=1, hours=3),
            body_preview='Good afternoon, our price for P/N 359042-15 is $84.00 ea. '
                         'Lead time is 45 ARO...',
            body_html='<p>STATZ Procurement,</p><p>Regarding your inquiry for '
                      'P/N 359042-15:</p><p>Unit Price: $84.00 each<br>'
                      'Lead time: 60 days ARO<br>Terms: Net 30</p>'
                      '<p>Please reference quote #TD-8841.</p>',
            headers_json={'Message-ID': '<demo-0003@titandefense.com>'},
            raw_payload={'demo': True},
            is_read=False,
            is_orphan=True,
        )

    # ── Small helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _status_for(stage):
        return {
            'unmatched': 'New',
            'matched': 'Active',
            'rfq_queued': 'RFQ_PENDING',
            'rfq_sent': 'RFQ_SENT',
            'won': 'BID_SUBMITTED',
            'lost_tight': 'BID_SUBMITTED',
            'lost_wide': 'BID_SUBMITTED',
            'pending': 'BID_SUBMITTED',
        }[stage]

    @staticmethod
    def _bq_template(spec):
        """
        A 121-cell BQ row with the DIBBS-supplied positions filled, so the BQ
        export path has a real template to overlay onto. Company-filled columns
        are intentionally left blank -- that is what the exporter writes.
        """
        row = [''] * 121
        row[0] = spec['sol']                                   # col 1
        row[1] = spec.get('sol_type') or 'T'                   # col 2
        row[2] = spec.get('set_aside') or 'N'                  # col 3
        row[3] = 'N'                                           # col 4
        row[4] = spec['due'].strftime('%m/%d/%Y')              # col 5
        row[43] = '0001'                                       # col 44
        row[45] = f'PR{spec["sol"][-8:]}'                      # col 46
        row[46] = spec['nsn']                                  # col 47
        row[47] = spec['uoi']                                  # col 48
        row[48] = str(spec['qty'])                             # col 49
        row[61] = 'N'                                          # col 62
        row[67] = 'N'                                          # col 68
        row[104] = 'P'                                         # col 105
        row[116] = 'N'                                         # col 117
        return row
