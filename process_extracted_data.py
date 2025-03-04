from datetime import datetime, timedelta
from django.db.models import Q
from .models import Buyer  # Assuming Buyer is the model for contracts_buyers

def process_extracted_data(extracted_data):
    processed_data = {}

    # Convert Contract Number to Text
    processed_data['contract_number'] = extracted_data.get('contract_number', 'Not found')

    # Convert Award Date to Date
    award_date_str = extracted_data.get('award_date', 'Not found')
    try:
        processed_data['award_date'] = datetime.strptime(award_date_str, '%Y %b %d').date()
    except ValueError:
        processed_data['award_date'] = None

    # Match Buyer to ID
    buyer_name = extracted_data.get('buyer', 'Not found')
    try:
        buyer = Buyer.objects.filter(Q(name__icontains=buyer_name)).first()
        processed_data['buyer_id'] = buyer.id if buyer else None
    except Buyer.DoesNotExist:
        processed_data['buyer_id'] = None

    # Convert PO Number to Text
    processed_data['po_number'] = extracted_data.get('po_number', 'Not found')

    # Convert Contract Type Purchase to Boolean
    processed_data['contract_type_purchase'] = extracted_data.get('contract_type_purchase', '') == 'X'

    # Convert Contract Type Delivery to Boolean
    processed_data['contract_type_delivery'] = extracted_data.get('contract_type_delivery', '') == 'X'

    # Calculate Due Date
    due_date_days_str = extracted_data.get('due_date_days', 'Not found')
    try:
        due_date_days = int(due_date_days_str.split()[0])
        processed_data['due_date'] = processed_data['award_date'] + timedelta(days=due_date_days)
    except (ValueError, TypeError):
        processed_data['due_date'] = None

    # Convert Contract Amount to Float
    contract_amount_str = extracted_data.get('contract_amount', 'Not found')
    try:
        processed_data['contract_amount'] = float(contract_amount_str.replace('$', '').replace(',', ''))
    except ValueError:
        processed_data['contract_amount'] = None

    return processed_data