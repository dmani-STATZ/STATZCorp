from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_POST
import csv
import io
import mimetypes

from .models import Campaign, CampaignRecipient, CampaignFollowUp, CampaignAttachment
from .forms import CampaignForm, CampaignRecipientImportForm, CampaignAIGenerateForm, CampaignFollowUpForm, CampaignAttachmentForm
from suppliers.models import Contact

@login_required
def campaign_list(request):
    campaigns = Campaign.objects.all().order_by('-created_at')
    return render(request, 'mailer/campaign_list.html', {'campaigns': campaigns})

@login_required
def campaign_create(request):
    if request.method == 'POST':
        form = CampaignForm(request.POST)
        if form.is_valid():
            campaign = form.save(commit=False)
            campaign.created_by = request.user
            campaign.save()
            messages.success(request, 'Campaign created successfully. You can now add recipients.')
            return redirect('mailer:campaign_detail', pk=campaign.pk)
    else:
        form = CampaignForm()
    return render(request, 'mailer/campaign_form.html', {'form': form, 'title': 'Create Campaign'})

@login_required
def campaign_edit(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if campaign.status not in ['DRAFT', 'FAILED']:
        messages.error(request, 'Cannot edit a campaign that is already scheduled or sent.')
        return redirect('mailer:campaign_detail', pk=campaign.pk)

    if request.method == 'POST':
        form = CampaignForm(request.POST, instance=campaign)
        if form.is_valid():
            form.save()
            messages.success(request, 'Campaign updated successfully.')
            return redirect('mailer:campaign_detail', pk=campaign.pk)
    else:
        form = CampaignForm(instance=campaign)
    return render(request, 'mailer/campaign_form.html', {'form': form, 'title': 'Edit Campaign'})

@login_required
def campaign_detail(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    recipients = campaign.recipients.all().order_by('-id')
    attachments = campaign.attachments.all().order_by('uploaded_at')
    attachment_form = CampaignAttachmentForm()
    return render(request, 'mailer/campaign_detail.html', {
        'campaign': campaign,
        'recipients': recipients,
        'attachments': attachments,
        'attachment_form': attachment_form,
    })

@login_required
def campaign_import_recipients(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if campaign.status not in ['DRAFT', 'FAILED']:
        messages.error(request, 'Cannot add recipients to a campaign that is already scheduled or sent.')
        return redirect('mailer:campaign_detail', pk=campaign.pk)

    if request.method == 'POST':
        form = CampaignRecipientImportForm(request.POST, request.FILES)
        if form.is_valid():
            emails_added = 0
            
            # 1. Process Text Box
            email_text = form.cleaned_data.get('email_text')
            if email_text:
                emails = [e.strip() for e in email_text.split(';') if e.strip()]
                for email in emails:
                    obj, created = CampaignRecipient.objects.get_or_create(
                        campaign=campaign,
                        email=email,
                        defaults={'status': 'PENDING'}
                    )
                    if created:
                        emails_added += 1

            # 2. Process CSV
            csv_file = request.FILES.get('csv_file')
            if csv_file:
                decoded_file = csv_file.read().decode('utf-8-sig')
                io_string = io.StringIO(decoded_file)
                reader = csv.DictReader(io_string)
                
                for row in reader:
                    email = row.get('email', '').strip()
                    if email:
                        first_name = row.get('first_name', '').strip()
                        last_name = row.get('last_name', '').strip()
                        company_name = row.get('company_name', '').strip()
                        
                        # Store any extra columns in custom_data
                        custom_data = {k: v for k, v in row.items() if k not in ['email', 'first_name', 'last_name', 'company_name']}
                        
                        # Look up supplier flags if possible
                        contact = Contact.objects.filter(email__iexact=email).select_related('supplier').first()
                        if contact and contact.supplier:
                            if contact.supplier.probation:
                                custom_data['is_probation'] = True
                            if contact.supplier.conditional:
                                custom_data['is_conditional'] = True
                        
                        obj, created = CampaignRecipient.objects.update_or_create(
                            campaign=campaign,
                            email=email,
                            defaults={
                                'first_name': first_name,
                                'last_name': last_name,
                                'company_name': company_name,
                                'custom_data': custom_data,
                                'status': 'PENDING'
                            }
                        )
                        if created:
                            emails_added += 1
                            
            messages.success(request, f'Successfully imported {emails_added} new recipients.')
            return redirect('mailer:campaign_detail', pk=campaign.pk)
    else:
        form = CampaignRecipientImportForm()
        
    return render(request, 'mailer/campaign_import.html', {
        'form': form,
        'campaign': campaign
    })

@login_required
def campaign_schedule(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if request.method == 'POST':
        if campaign.recipients.count() == 0:
            messages.error(request, 'Cannot schedule a campaign with no recipients.')
        elif campaign.status == 'DRAFT':
            campaign.status = 'SCHEDULED'
            campaign.save(update_fields=['status'])
            messages.success(request, 'Campaign has been scheduled for sending. It will be dispatched in the background.')
        else:
            messages.error(request, f'Campaign is already {campaign.status}.')
            
    return redirect('mailer:campaign_detail', pk=campaign.pk)

@login_required
def campaign_audience(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if campaign.status not in ['DRAFT', 'FAILED']:
        messages.error(request, 'Cannot build an audience for a campaign that is already scheduled or sent.')
        return redirect('mailer:campaign_detail', pk=campaign.pk)

    from .forms import AudienceBuilderForm
    from .services.audience_builder import build_audience_by_years

    if request.method == 'POST':
        form = AudienceBuilderForm(request.POST)
        if form.is_valid():
            target_years = form.cleaned_data.get('target_years')
            added_count = build_audience_by_years(campaign, request.active_company, target_years)
            messages.success(request, f'Successfully built audience! Added {added_count} recipients based on contract history.')
            return redirect('mailer:campaign_detail', pk=campaign.pk)
    else:
        form = AudienceBuilderForm()
        
    return render(request, 'mailer/campaign_audience.html', {
        'form': form,
        'campaign': campaign
    })

@login_required
def recipient_preview(request, pk):
    recipient = get_object_or_404(CampaignRecipient, pk=pk)
    campaign = recipient.campaign
    
    context = {
        'first_name': recipient.first_name or '',
        'last_name': recipient.last_name or '',
        'company_name': recipient.company_name or '',
        'email': recipient.email or '',
        **recipient.custom_data
    }
    
    try:
        subject = campaign.subject_template.format(**context)
    except KeyError as e:
        subject = campaign.subject_template.replace('{' + str(e.args[0]) + '}', '')
        
    try:
        body = campaign.body_template.format(**context)
    except KeyError as e:
        body = campaign.body_template.replace('{' + str(e.args[0]) + '}', '')
        
    attachments = campaign.attachments.all()
    return render(request, 'mailer/recipient_preview.html', {
        'recipient': recipient,
        'campaign': campaign,
        'subject': subject,
        'body': body,
        'attachments': attachments,
    })

@login_required
@require_POST
def recipient_delete(request, pk):
    recipient = get_object_or_404(CampaignRecipient, pk=pk)
    campaign_pk = recipient.campaign.pk
    recipient.delete()
    messages.success(request, f"Recipient {recipient.email} removed from campaign.")
    return redirect('mailer:campaign_detail', pk=campaign_pk)

@login_required
def campaign_generate_ai(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    
    if request.method == 'POST':
        form = CampaignAIGenerateForm(request.POST, instance=campaign)
        if form.is_valid():
            campaign = form.save(commit=False)
            campaign.ai_status = 'PROCESSING'
            campaign.save()
            messages.info(request, "AI Generation has been scheduled. It may take a few minutes depending on the number of recipients.")
            return redirect('mailer:campaign_detail', pk=campaign.pk)
    else:
        form = CampaignAIGenerateForm(instance=campaign)
        
    return render(request, 'mailer/campaign_generate_ai.html', {
        'form': form,
        'campaign': campaign,
        'title': 'Generate AI Messages'
    })

@login_required
@require_POST
def recipient_toggle_followup(request, pk):
    recipient = get_object_or_404(CampaignRecipient, pk=pk)
    recipient.follow_up_active = not recipient.follow_up_active
    recipient.save()
    messages.success(request, f"Follow-ups {'enabled' if recipient.follow_up_active else 'disabled'} for {recipient.email}.")
    return redirect('mailer:campaign_detail', pk=recipient.campaign.pk)

@login_required
@require_POST
def campaign_toggle_followup(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    campaign.follow_up_enabled = not campaign.follow_up_enabled
    campaign.save()
    messages.success(request, f"Campaign follow-ups {'enabled' if campaign.follow_up_enabled else 'disabled'}.")
    return redirect('mailer:campaign_detail', pk=campaign.pk)

@login_required
def campaign_followup_add(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    
    if request.method == 'POST':
        form = CampaignFollowUpForm(request.POST)
        if form.is_valid():
            followup = form.save(commit=False)
            followup.campaign = campaign
            # Auto-assign step number
            existing = campaign.follow_ups.count()
            followup.step_number = existing + 1
            followup.save()
            messages.success(request, f"Added Follow-Up Step {followup.step_number}")
            return redirect('mailer:campaign_detail', pk=campaign.pk)
    else:
        form = CampaignFollowUpForm()
        
    return render(request, 'mailer/campaign_followup_form.html', {
        'form': form,
        'campaign': campaign,
        'title': 'Add Follow-Up Step'
    })

@login_required
def campaign_followup_edit(request, pk, followup_pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    followup = get_object_or_404(CampaignFollowUp, pk=followup_pk, campaign=campaign)
    
    if request.method == 'POST':
        form = CampaignFollowUpForm(request.POST, instance=followup)
        if form.is_valid():
            form.save()
            messages.success(request, "Follow-Up updated.")
            return redirect('mailer:campaign_detail', pk=campaign.pk)
    else:
        form = CampaignFollowUpForm(instance=followup)
        
    return render(request, 'mailer/campaign_followup_form.html', {
        'form': form,
        'campaign': campaign,
        'title': f'Edit Follow-Up Step {followup.step_number}'
    })

@login_required
@require_POST
def campaign_followup_delete(request, pk, followup_pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    followup = get_object_or_404(CampaignFollowUp, pk=followup_pk, campaign=campaign)
    step_num = followup.step_number
    followup.delete()
    
    # Reorder remaining steps
    for idx, remaining in enumerate(campaign.follow_ups.order_by('step_number'), start=1):
        if remaining.step_number != idx:
            remaining.step_number = idx
            remaining.save()
            
    messages.success(request, f"Follow-Up Step {step_num} deleted.")
    return redirect('mailer:campaign_detail', pk=campaign.pk)

@login_required
@require_POST
def campaign_attachment_add(request, pk):
    campaign = get_object_or_404(Campaign, pk=pk)
    if campaign.status not in ['DRAFT', 'FAILED']:
        messages.error(request, 'Cannot add attachments to a campaign that is already scheduled or sent.')
        return redirect('mailer:campaign_detail', pk=campaign.pk)

    form = CampaignAttachmentForm(request.POST, request.FILES)
    if form.is_valid():
        uploaded = form.cleaned_data['file']
        mime_type, _ = mimetypes.guess_type(uploaded.name)
        if not mime_type:
            mime_type = 'application/octet-stream'

        CampaignAttachment.objects.create(
            campaign=campaign,
            file=uploaded,
            original_name=uploaded.name,
            content_type=mime_type,
            file_size=uploaded.size,
        )
        messages.success(request, f'Attached "{uploaded.name}" ({uploaded.size / (1024*1024):.1f} MB).')
    else:
        for error in form.errors.get('file', []):
            messages.error(request, error)

    return redirect('mailer:campaign_detail', pk=campaign.pk)

@login_required
@require_POST
def campaign_attachment_delete(request, pk):
    attachment = get_object_or_404(CampaignAttachment, pk=pk)
    campaign_pk = attachment.campaign.pk
    name = attachment.original_name
    # Delete the physical file from storage
    if attachment.file:
        attachment.file.delete(save=False)
    attachment.delete()
    messages.success(request, f'Removed attachment "{name}".')
    return redirect('mailer:campaign_detail', pk=campaign_pk)
