import json
import logging
import math
from mailer.models import Campaign
from core.anthropic_client import call_anthropic

logger = logging.getLogger("mailer.background_tasks")

def process_ai_snippets():
    """
    Finds campaigns in the 'PROCESSING' AI status, and batches their recipients through Anthropic
    to generate custom messages. Saves the resulting messages into custom_data.
    """
    campaigns = Campaign.objects.filter(ai_status='PROCESSING')
    
    for campaign in campaigns:
        try:
            logger.info(f"Starting AI generation for campaign: {campaign.name}")
            
            # Find recipients who don't have an ai_custom_message yet
            recipients = campaign.recipients.all()
            pending_recipients = []
            for r in recipients:
                if 'ai_custom_message' not in r.custom_data:
                    pending_recipients.append(r)
            
            if not pending_recipients:
                # All done
                campaign.ai_status = 'COMPLETED'
                campaign.save(update_fields=['ai_status'])
                continue
                
            # Batch them into chunks of 30
            BATCH_SIZE = 30
            num_batches = math.ceil(len(pending_recipients) / BATCH_SIZE)
            
            for i in range(num_batches):
                batch = pending_recipients[i*BATCH_SIZE:(i+1)*BATCH_SIZE]
                
                # Prepare JSON payload for Anthropic
                recipients_data = []
                for r in batch:
                    # Strip out ai_custom_message if it somehow exists to save tokens
                    stats = {k: v for k, v in r.custom_data.items() if k != 'ai_custom_message'}
                    recipients_data.append({
                        "id": r.pk,
                        "company": r.company_name,
                        "name": f"{r.first_name} {r.last_name}".strip(),
                        "stats": stats
                    })
                
                system_prompt = (
                    "You are an expert sales copywriter. You will receive an instruction and a JSON list of recipients with their data. "
                    "You must output a JSON array of objects with exactly two keys: 'id' (the integer ID) and 'message' (the generated text). "
                    "Do not output any other text or markdown formatting. Output raw valid JSON only."
                )
                
                user_prompt = f"Instruction: {campaign.ai_instruction}\n\nRecipients:\n{json.dumps(recipients_data)}"
                
                payload = {
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 4096,
                    "system": system_prompt,
                    "messages": [
                        {"role": "user", "content": user_prompt}
                    ]
                }
                
                # Call LLM
                response = call_anthropic(payload, call_site=f"mailer.campaign_{campaign.pk}.ai")
                
                # Parse response
                content = response.get("content", [])
                if not content:
                    raise ValueError("Anthropic returned empty content.")
                
                text_response = content[0].get("text", "")
                
                try:
                    generated_items = json.loads(text_response)
                except json.JSONDecodeError:
                    # Sometimes the LLM wraps it in ```json
                    if text_response.startswith("```json"):
                        text_response = text_response[7:]
                    if text_response.endswith("```"):
                        text_response = text_response[:-3]
                    generated_items = json.loads(text_response.strip())
                
                # Apply updates
                updates = []
                for item in generated_items:
                    r_id = item.get("id")
                    message = item.get("message")
                    
                    # Find recipient in batch
                    recipient = next((r for r in batch if r.pk == r_id), None)
                    if recipient and message:
                        recipient.custom_data['ai_custom_message'] = message
                        updates.append(recipient)
                
                # Save batch
                for recipient in updates:
                    recipient.save(update_fields=['custom_data'])
                    
            # Double check if any are still pending
            still_pending = False
            for r in campaign.recipients.all():
                if 'ai_custom_message' not in r.custom_data:
                    still_pending = True
                    break
            
            if not still_pending:
                campaign.ai_status = 'COMPLETED'
            else:
                campaign.ai_status = 'FAILED'
                logger.error(f"Campaign {campaign.name} finished AI generation but some recipients are still missing messages.")
                
            campaign.save(update_fields=['ai_status'])
            
        except Exception as e:
            logger.exception(f"Failed to generate AI messages for campaign {campaign.name}: {e}")
            campaign.ai_status = 'FAILED'
            campaign.save(update_fields=['ai_status'])
