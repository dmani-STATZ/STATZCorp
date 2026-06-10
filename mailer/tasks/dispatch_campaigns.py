import logging
from django.utils import timezone
from mailer.models import Campaign
from mailer.services.graph_mail import send_mail_via_graph

logger = logging.getLogger("mailer.background_tasks")

def dispatch_campaigns():
    """
    Finds campaigns that are SCHEDULED or SENDING and dispatches their pending recipients.
    Changes campaign status to COMPLETED when all recipients are processed.
    """
    campaigns = Campaign.objects.filter(status__in=['SCHEDULED', 'SENDING'])
    
    for campaign in campaigns:
        if campaign.status == 'SCHEDULED':
            campaign.status = 'SENDING'
            campaign.save(update_fields=['status'])
            logger.info(f"Started sending campaign '{campaign.name}'")

        pending_recipients = campaign.recipients.filter(status='PENDING')
        
        # In a real heavy-duty environment, we'd chunk this.
        # But this is a basic implementation for V1.
        for recipient in pending_recipients:
            # 1. Build context for formatting
            context = {
                'first_name': recipient.first_name or '',
                'last_name': recipient.last_name or '',
                'company_name': recipient.company_name or '',
                'email': recipient.email or '',
                **recipient.custom_data
            }
            
            # 2. Format subject and body using safe dictionary formatting
            try:
                subject = campaign.subject_template.format(**context)
            except KeyError as e:
                subject = campaign.subject_template.replace('{' + str(e.args[0]) + '}', '')
                
            try:
                body = campaign.body_template.format(**context)
            except KeyError as e:
                body = campaign.body_template.replace('{' + str(e.args[0]) + '}', '')

            # 3. Send email via Graph API
            success = send_mail_via_graph(
                to_address=recipient.email,
                subject=subject,
                body=body,
                sender=campaign.sender_email
            )
            
            # 4. Update recipient status
            if success:
                recipient.status = 'SENT'
                recipient.sent_at = timezone.now()
            else:
                recipient.status = 'FAILED'
                recipient.error_message = "Microsoft Graph API returned an error. Check server logs."
                
            recipient.save(update_fields=['status', 'sent_at', 'error_message'])

        # Check if all done
        if not campaign.recipients.filter(status='PENDING').exists():
            campaign.status = 'COMPLETED'
            campaign.save(update_fields=['status'])
            logger.info(f"Finished campaign '{campaign.name}'")
