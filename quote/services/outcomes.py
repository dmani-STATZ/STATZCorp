"""
Phase 4: post-award reconciliation and "Our Bids" intelligence.

Reconciliation matches each submitted bid (its frozen ``BidOutcome``) to the
DIBBS award for the same solicitation line:

  * award rows for the solicitation (FK, or the indexed ``sol_number``);
  * narrowed to the line by purchase-request number, else NSN, else -- only
    when the solicitation has a single line -- any award for it;
  * a priced award beats a "faux" placeholder (a MOD that arrived before the
    award: it names the winner but carries no price), latest first.

WON when the awardee CAGE is one of our active CAGEs, else LOST. The DIBBS
award file publishes neither quantity nor unit price, so the award unit price
is DERIVED: total contract price / our line quantity. It is flagged as derived
everywhere and is an approximation on multi-line awards.

Outcomes whose award is missing or faux are re-checked on every run, so a
later real award upgrades them.
"""
import logging
from collections import Counter
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from dibbs.models import CompanyCAGE, DibbsAward, SAMEntityCache
from quote.models import BidOutcome
from quote.services import cost
from quote.services.matching import normalize_nsn
from suppliers.models import Supplier

logger = logging.getLogger(__name__)

UNIT_Q = Decimal('0.00001')
PCT_Q = Decimal('0.0001')
TIGHT_PCT = Decimal('5')
TREND_YEARS = 2


# ── Names ────────────────────────────────────────────────────────────────────

def entity_names(cages):
    """{CAGE: display name} from our CAGEs, the supplier directory, cached SAM."""
    cages = {c.upper() for c in cages if c}
    names = {}
    for cage in SAMEntityCache.objects.filter(cage_code__in=cages).exclude(entity_name=''):
        names[cage.cage_code.upper()] = cage.entity_name
    for s in Supplier.objects.filter(cage_code__in=cages).exclude(name__isnull=True).exclude(name=''):
        names[(s.cage_code or '').upper()] = s.name
    for c in CompanyCAGE.objects.filter(cage_code__in=cages).select_related('company'):
        names[c.cage_code.upper()] = (c.company.name if c.company_id else '') or c.company_name or 'STATZ'
    return names


def our_cages():
    return {c.upper() for c in CompanyCAGE.objects.filter(is_active=True).values_list('cage_code', flat=True)}


# ── Matching ─────────────────────────────────────────────────────────────────

def find_award(bid):
    line = bid.line
    sol = line.solicitation
    # sol_number is indexed (900k+ rows); dibbs_solicitation_number carries
    # the same value but is not, so never filter on it here.
    awards = DibbsAward.objects.filter(
        Q(solicitation=sol) | Q(sol_number=sol.solicitation_number)
    ).exclude(awardee_cage='')
    pr = (line.purchase_request_number or '').strip()
    nsn13 = normalize_nsn(line.nsn)
    candidates = []
    if pr:
        candidates = list(awards.filter(purchase_request=pr))
        # An award that names a different purchase request belongs to another
        # line, even when the NSN matches (same NSN on two lines happens).
        awards = awards.filter(Q(purchase_request__isnull=True) | Q(purchase_request='') | Q(purchase_request=pr))
    if not candidates and nsn13:
        candidates = list(awards.filter(nsn__in=[nsn13, line.nsn]))
    if not candidates and sol.lines.count() == 1:
        candidates = list(awards)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda a: (a.is_faux, not a.total_contract_price, -a.award_date.toordinal(), -a.pk),
    )[0]


def apply_award(outcome, award, ours, names):
    """Fill outcome fields from an award (or reset to PENDING when None)."""
    now = timezone.now()
    if award is None:
        outcome.award = None
        outcome.outcome = BidOutcome.OUTCOME_PENDING
        outcome.reconciled_at = now
        return outcome
    bid = outcome.bid
    cage = (award.awardee_cage or '').upper()
    qty = bid.line.quantity or 0
    outcome.award = award
    outcome.winning_cage = cage
    outcome.winning_entity_name = names.get(cage, '')[:255]
    outcome.outcome = BidOutcome.OUTCOME_WON if cage in ours else BidOutcome.OUTCOME_LOST
    outcome.award_total_price = award.total_contract_price
    outcome.award_quantity = qty or None
    outcome.award_unit_price_is_derived = True
    unit = None
    if award.total_contract_price and qty:
        unit = (Decimal(award.total_contract_price) / qty).quantize(UNIT_Q, ROUND_HALF_UP)
    outcome.award_unit_price = unit
    if unit:
        outcome.dollar_delta = (outcome.our_unit_price - unit).quantize(UNIT_Q, ROUND_HALF_UP)
        outcome.pct_spread = ((outcome.our_unit_price - unit) / unit * 100).quantize(PCT_Q, ROUND_HALF_UP)
    else:
        outcome.dollar_delta = None
        outcome.pct_spread = None
    outcome.within_5_pct = bool(
        outcome.outcome == BidOutcome.OUTCOME_LOST
        and outcome.pct_spread is not None
        and Decimal('0') < outcome.pct_spread <= TIGHT_PCT
    )
    outcome.reconciled_at = now
    return outcome


def reconcile(outcomes=None):
    """
    Re-check pending outcomes and those resting on a faux award. Returns
    {'checked', 'won', 'lost', 'still_pending'}.
    """
    if outcomes is None:
        outcomes = BidOutcome.objects.filter(
            Q(outcome=BidOutcome.OUTCOME_PENDING) | Q(award__is_faux=True) | Q(award__isnull=True)
        )
    outcomes = list(outcomes.select_related('bid__line__solicitation', 'award'))
    ours = our_cages()
    pairs = [(o, find_award(o.bid)) for o in outcomes]
    names = entity_names({(a.awardee_cage or '') for _, a in pairs if a})
    summary = Counter(checked=len(pairs))
    for outcome, award in pairs:
        apply_award(outcome, award, ours, names)
        outcome.save()
        summary[{'WON': 'won', 'LOST': 'lost'}.get(outcome.outcome, 'still_pending')] += 1
    result = {k: summary.get(k, 0) for k in ('checked', 'won', 'lost', 'still_pending')}
    logger.info('bid outcome reconciliation: %s', result)
    return result


# ── Our Bids dataset ─────────────────────────────────────────────────────────

def rows():
    """Every outcome as a compact dict for the Our Bids grid (filtered in the browser)."""
    out = []
    for o in (
        BidOutcome.objects.select_related('bid__line__solicitation', 'award')
        .order_by('-submission_date', '-pk')
    ):
        line = o.bid.line
        qty = line.quantity or 0
        out.append({
            'id': o.pk,
            'status': o.outcome,
            'sol': line.solicitation.solicitation_number,
            'nsn': line.nsn,
            'nomen': line.nomenclature or '',
            'bidDate': o.submission_date.isoformat(),
            'ourPrice': float(o.our_unit_price),
            'awardPrice': float(o.award_unit_price) if o.award_unit_price is not None else None,
            'delta': float(o.dollar_delta) if o.dollar_delta is not None else None,
            'pct': float(o.pct_spread) if o.pct_spread is not None else None,
            'tight': o.within_5_pct,
            'winner': o.winning_entity_name or o.winning_cage or '',
            'cage': o.winning_cage,
            'margin': float(o.snapshot_margin_pct) if o.snapshot_margin_pct is not None else None,
            'value': float(o.our_unit_price * qty) if qty else None,
            'awardTotal': float(o.award_total_price) if o.award_total_price is not None else None,
            'supplier': o.snapshot_supplier_name,
        })
    return out


# ── Competitive trend analysis (forensic drawer) ─────────────────────────────

def _money(d):
    return f'${Decimal(d):,.2f}'


def trends(outcome):
    """Plain-language observations for one bid, from our history and DLA awards."""
    notes = []
    line = outcome.bid.line
    nsn13 = normalize_nsn(line.nsn)
    fsc = nsn13[:4]
    since = timezone.localdate() - timedelta(days=365 * TREND_YEARS)

    # Our record on this NSN.
    ours = BidOutcome.objects.filter(bid__line__nsn__in=[line.nsn, nsn13]).exclude(
        outcome=BidOutcome.OUTCOME_PENDING)
    decided = ours.count()
    if decided > 1:
        won = ours.filter(outcome=BidOutcome.OUTCOME_WON).count()
        notes.append(f'We have won {won} of {decided} decided bids on this NSN.')

    # What-if at the lowest preset markup.
    if (outcome.outcome == BidOutcome.OUTCOME_LOST and outcome.award_unit_price
            and outcome.snapshot_supplier_unit_cost is not None):
        landed = (outcome.snapshot_supplier_unit_cost + outcome.snapshot_packaging_adder_unit
                  + outcome.snapshot_freight_adder_unit)
        floor = cost.price_from_markup(landed, cost.MARKUP_PRESETS[0])
        if landed >= outcome.award_unit_price:
            notes.append(
                f'Our landed cost ({_money(landed)}) was already at or above the '
                f'winning price ({_money(outcome.award_unit_price)}): no markup would have won. '
                'The supplier cost is the problem, not the margin.')
        elif floor <= outcome.award_unit_price:
            notes.append(
                f'At a {cost.MARKUP_PRESETS[0]}% markup we would have bid {_money(floor)}, '
                f'under the winning {_money(outcome.award_unit_price)}.')
        else:
            notes.append(
                f'Even at {cost.MARKUP_PRESETS[0]}% markup ({_money(floor)}) we would have '
                f'been above the winning {_money(outcome.award_unit_price)}.')

    # Who wins this NSN / FSC at DLA.
    awards = DibbsAward.objects.filter(award_date__gte=since, is_faux=False).exclude(awardee_cage='')
    nsn_wins = Counter(
        awards.filter(nsn=nsn13).values_list('awardee_cage', flat=True)) if nsn13 else Counter()
    if nsn_wins:
        top = nsn_wins.most_common(3)
        names = entity_names([c for c, _ in top])
        listed = ', '.join(f'{names.get(c, c)} ({n})' for c, n in top)
        notes.append(f'DLA awards on this NSN in the last {TREND_YEARS} years: {listed}.')
    if outcome.winning_cage and fsc:
        fsc_wins = awards.filter(nsn__startswith=fsc, awardee_cage=outcome.winning_cage).count()
        if fsc_wins > 1:
            who = outcome.winning_entity_name or outcome.winning_cage
            notes.append(f'{who} has won {fsc_wins} awards in FSC {fsc} in the last {TREND_YEARS} years.')

    # Is this supplier competitive for us?
    if outcome.snapshot_supplier_name:
        by_supplier = BidOutcome.objects.filter(
            snapshot_supplier_name=outcome.snapshot_supplier_name,
        ).exclude(outcome=BidOutcome.OUTCOME_PENDING)
        total = by_supplier.count()
        if total > 1:
            lost = by_supplier.filter(outcome=BidOutcome.OUTCOME_LOST)
            spreads = [s for s in lost.values_list('pct_spread', flat=True) if s is not None]
            avg = (sum(spreads) / len(spreads)).quantize(Decimal('0.1')) if spreads else None
            text = f'Bids built on {outcome.snapshot_supplier_name}: lost {lost.count()} of {total}'
            notes.append(text + (f', averaging {avg:+}% over the winner.' if avg is not None else '.'))

    if outcome.outcome == BidOutcome.OUTCOME_PENDING and not notes:
        notes.append('No award posted yet. Reconciliation re-checks pending bids every hour.')
    return notes
