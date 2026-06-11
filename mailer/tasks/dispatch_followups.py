import logging
from django.utils.timezone import now
from datetime import timedelta
from mailer.models import Campaign
from mailer.services.graph_mail import send_email_via_graph

logger = logging.getLogger("mailer.background_tasks")

def dispatch_followups():
    """
    Finds campaigns that are completed and have follow-ups enabled.
    Checks recipients to see if they are due for the next step.
    """
    # Only look at campaigns where the initial send completed
    campaigns = Campaign.objects.filter(status='COMPLETED', follow_up_enabled=True)
    
    current_time = now()
    
    for campaign in campaigns:
        # Get ordered follow up steps
        follow_ups = list(campaign.follow_ups.all())
        if not follow_ups:
            continue
            
        # Get recipients who successfully received the initial email and still have follow-ups active
        recipients = campaign.recipients.filter(status='SENT', follow_up_active=True)
        
        for recipient in recipients:
            # Check if there are still steps left for this recipient
            if recipient.current_followup_step < len(follow_ups):
                next_step = follow_ups[recipient.current_followup_step]
                
                # Determine when the last email was sent
                reference_date = recipient.last_contact_date or recipient.sent_at
                
                if not reference_date:
                    continue # Shouldn't happen since status='SENT' implies sent_at is set
                    
                # Calculate if enough days have passed
                days_passed = (current_time - reference_date).days
                
                if days_passed >= next_step.delay_days:
                    # Time to send!
                    try:
                        # Prepare subject
                        subject = next_step.subject_template
                        if not subject:
                            # Default Re: logic
                            original_subject = campaign.subject_template or "Update"
                            if not original_subject.lower().startswith("re:"):
                                subject = f"Re: {original_subject}"
                            else:
                                subject = original_subject
                                
                        # Use formatting just like the main dispatch
                        # We use the recipient's custom_data as kwargs
                        context = {
                            'first_name': recipient.first_name or '',
                            'last_name': recipient.last_name or '',
                            'company_name': recipient.company_name or '',
                            'email': recipient.email,
                            **recipient.custom_data
                        }
                        
                        try:
                            final_subject = subject.format(**context)
                            final_body = next_step.body_template.format(**context)
                        except KeyError as e:
                            logger.error(f"Template formatting failed for {recipient.email} on step {next_step.step_number}: Missing key {e}")
                            # Stop follow-ups for this person to prevent infinite loops of errors
                            recipient.follow_up_active = False
                            recipient.error_message = f"Follow-Up {next_step.step_number} format error: missing {e}"
                            recipient.save(update_fields=['follow_up_active', 'error_message'])
                            continue
                            
                        # Send via Graph
                        success, error = send_email_via_graph(
                            sender_address=campaign.sender_email,
                            recipient_address=recipient.email,
                            subject=final_subject,
                            body=final_body,
                            is_html=True # Keep true if we support HTML body
                        )
                        
                        if success:
                            # Update recipient progress
                            recipient.current_followup_step += 1
                            recipient.last_contact_date = current_time
                            recipient.error_message = "" # Clear old errors
                            recipient.save(update_fields=['current_followup_step', 'last_contact_date', 'error_message'])
                            logger.info(f"Sent follow-up step {next_step.step_number} to {recipient.email}")
                        else:
                            # Don't increment step, but maybe disable follow-up or log error
                            recipient.error_message = f"Follow-Up {next_step.step_number} failed: {error}"
                            recipient.save(update_fields=['error_message'])
                            logger.error(f"Failed to send follow-up step {next_step.step_number} to {recipient.email}: {error}")
                            
                    except Exception as e:
                        logger.exception(f"Unexpected error processing follow-up for {recipient.email}: {e}")
                        
