from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import Coalesce
from contracts.models import Clin
from suppliers.models import Contact
from mailer.models import CampaignRecipient
import logging

logger = logging.getLogger(__name__)

@transaction.atomic
def build_audience_by_years(campaign, active_company, target_years):
    """
    Finds all supplier contacts associated with contracts won in the given target_years.
    Injects the contract win counts per year into the recipient's custom_data.
    Canceled contracts are excluded.
    Returns the number of recipients added.
    """
    if not target_years:
        return 0

    # Ensure target_years are integers
    target_years = [int(y) for y in target_years]

    # Build the annotation dictionary dynamically based on selected years
    # We want to know how many distinct contracts a supplier won in each year
    annotations = {}
    for year in target_years:
        annotations[f'won_{year}'] = Count(
            'contract_id',
            filter=Q(contract__award_date__year=year),
            distinct=True
        )

    # 1. Query Clin for Suppliers that won a contract in the target years
    # Exclude contracts with status 'Canceled'
    # Must match the active company context
    supplier_stats = Clin.objects.filter(
        contract__company=active_company,
        contract__award_date__year__in=target_years,
        supplier__isnull=False
    ).exclude(
        contract__status__description='Canceled'
    ).values('supplier_id').annotate(**annotations)

    if not supplier_stats:
        return 0

    # Map supplier ID to their calculated stats
    # e.g. { 45: {"won_2023": 12, "won_2024": 7} }
    stats_map = {}
    supplier_ids = []
    for stat in supplier_stats:
        sid = stat['supplier_id']
        supplier_ids.append(sid)
        stats_map[sid] = {f'won_{year}': stat.get(f'won_{year}', 0) for year in target_years}

    # 2. Find Contacts for these Suppliers who have valid emails
    contacts = Contact.objects.filter(
        supplier_id__in=supplier_ids,
        email__isnull=False
    ).exclude(email='').select_related('supplier')

    # Keep track of existing emails in this campaign to avoid IntegrityError
    existing_emails = set(
        CampaignRecipient.objects.filter(campaign=campaign).values_list('email', flat=True)
    )

    new_recipients = []
    
    # We may have multiple contacts with the same email across different suppliers.
    # We'll just take the first one we encounter for the campaign to keep it simple,
    # or rely on the `existing_emails` set.
    for contact in contacts:
        email = contact.email.strip().lower()
        if not email or email in existing_emails:
            continue
            
        # Get the stats for this contact's supplier
        custom_data = stats_map.get(contact.supplier_id, {})
        
        # Add probation and conditional flags
        if contact.supplier:
            if contact.supplier.probation:
                custom_data['is_probation'] = True
            if contact.supplier.conditional:
                custom_data['is_conditional'] = True
        
        # Split name (heuristic for first/last)
        name_parts = (contact.name or "").split(" ", 1)
        first_name = name_parts[0] if len(name_parts) > 0 else ""
        last_name = name_parts[1] if len(name_parts) > 1 else ""
        
        company_name = contact.supplier.name if contact.supplier else ""

        recipient = CampaignRecipient(
            campaign=campaign,
            email=email,
            first_name=first_name,
            last_name=last_name,
            company_name=company_name,
            custom_data=custom_data,
            status='PENDING'
        )
        new_recipients.append(recipient)
        existing_emails.add(email) # Prevent duplicates in this batch

    # 3. Bulk create
    if new_recipients:
        CampaignRecipient.objects.bulk_create(new_recipients)
        
    return len(new_recipients)
