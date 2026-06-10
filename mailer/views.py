from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
import csv
import io

from .models import Campaign, CampaignRecipient
from .forms import CampaignForm, CampaignRecipientImportForm

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
    return render(request, 'mailer/campaign_detail.html', {
        'campaign': campaign,
        'recipients': recipients,
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
