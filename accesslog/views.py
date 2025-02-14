from django.shortcuts import render, redirect, get_object_or_404
from STATZWeb.decorators import conditional_login_required
from django.utils import timezone
from .models import Visitor, Staged
from .forms import VisitorCheckInForm, MonthYearForm
from django.http import HttpResponse, JsonResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
import io
from datetime import datetime
from django.contrib import messages

# Create your views here.

@conditional_login_required
def visitor_log(request):
    visitors = Visitor.objects.all().order_by('-date_of_visit', '-time_in')
    month_year_form = MonthYearForm()
    context = {
        'visitors': visitors,
        'month_year_form': month_year_form,
        'title': 'Visitor Log'
    }
    return render(request, 'accesslog/visitor_log.html', context)

@conditional_login_required
def check_in_visitor(request):
    if request.method == 'POST':
        form = VisitorCheckInForm(request.POST)
        if form.is_valid():
            action = request.POST.get('action', 'check_in')
            
            if action == 'stage':
                # Save to staged table
                Staged.objects.create(
                    visitor_name=form.cleaned_data['visitor_name'],
                    visitor_company=form.cleaned_data['visitor_company'],
                    reason_for_visit=form.cleaned_data['reason_for_visit'],
                    is_us_citizen=form.cleaned_data['is_us_citizen']
                )
                messages.success(request, 'Visitor has been staged for later check-in')
            else:
                # Create the visitor record
                visitor = form.save(commit=False)
                visitor.time_in = timezone.now()  # Use full datetime
                visitor.date_of_visit = timezone.now().date()  # Set date from timezone-aware time
                visitor.save()
                
                # Check if this was a staged visitor and delete if it was
                staged_id = request.POST.get('staged_id')
                print(f"Staged ID: {staged_id}")  # Debug line
                if staged_id and staged_id != '0':
                    try:
                        staged = Staged.objects.get(id=staged_id)
                        staged.delete()
                        messages.success(request, f'{visitor.visitor_name} has been checked in and removed from staged visitors')
                    except Staged.DoesNotExist:
                        print(f"No staged visitor found with ID: {staged_id}")  # Debug line
                        pass
                else:
                    messages.success(request, f'{visitor.visitor_name} has been checked in')
                
            return redirect('accesslog:visitor_log')
    else:
        # Create a fresh form with updated choices
        form = VisitorCheckInForm()
        form.fields['visitor_history'].populate_choices()
    
    return render(request, 'accesslog/check_in.html', {'form': form, 'title': 'Check In Visitor'})

@conditional_login_required
def check_out_visitor(request, visitor_id):
    visitor = Visitor.objects.get(id=visitor_id)
    visitor.time_out = timezone.now()  # Use full datetime
    visitor.departed = True
    visitor.save()
    return redirect('accesslog:visitor_log')

@conditional_login_required
def generate_report(request):
    if request.method == 'POST':
        form = MonthYearForm(request.POST)
        if form.is_valid():
            month_year = form.cleaned_data['month_year']
            year, month = map(int, month_year.split('-'))
            
            # Get visitors for selected month/year
            visitors = Visitor.objects.filter(
                date_of_visit__year=year,
                date_of_visit__month=month
            ).order_by('date_of_visit', 'time_in')

            # Create PDF
            buffer = io.BytesIO()
            
            # Create the PDF object using letter size
            p = canvas.Canvas(buffer, pagesize=letter)
            width, height = letter  # Get page dimensions
            
            # Add header
            p.setFont("Helvetica-Bold", 24)
            p.drawString(50, height - 50, "STATZ Corporation")
            p.setFont("Helvetica", 16)
            month_name = visitors.first().date_of_visit.strftime('%B %Y') if visitors.exists() else month_year
            p.drawString(50, height - 80, f"Visitor Log - {month_name}")
            
            # Add table headers
            p.setFont("Helvetica-Bold", 12)
            headers = ['Date', 'Name', 'Company', 'Reason', 'Time In', 'Time Out']
            x_positions = [50, 130, 230, 330, 430, 480]
            y = height - 120
            
            for header, x in zip(headers, x_positions):
                p.drawString(x, y, header)
            
            # Add horizontal line under headers
            p.line(50, y - 5, 550, y - 5)
            
            # Add visitor data
            p.setFont("Helvetica", 10)
            y -= 25  # Start below the header line
            
            for visitor in visitors:
                # Check if we need a new page
                if y < 50:
                    p.showPage()
                    y = height - 50
                    # Redraw headers on new page
                    p.setFont("Helvetica-Bold", 12)
                    for header, x in zip(headers, x_positions):
                        p.drawString(x, y, header)
                    p.line(50, y - 5, 550, y - 5)
                    p.setFont("Helvetica", 10)
                    y -= 25

                data = [
                    visitor.date_of_visit.strftime('%m/%d/%Y'),
                    visitor.visitor_name,
                    visitor.visitor_company,
                    visitor.reason_for_visit,
                    visitor.time_in.strftime('%I:%M %p'),
                    visitor.time_out.strftime('%I:%M %p') if visitor.time_out else ''
                ]
                
                for text, x in zip(data, x_positions):
                    # Truncate text if too long
                    if len(text) > 20 and x not in [50, 430, 480]:  # Don't truncate date and times
                        text = text[:17] + '...'
                    p.drawString(x, y, text)
                
                y -= 20  # Move down for next row
            
            # Add footer
            p.setFont("Helvetica-Oblique", 8)
            p.drawString(50, 30, f"Generated on {timezone.now().strftime('%m/%d/%Y %I:%M %p')}")
            p.drawString(450, 30, "Page 1")
            
            # Save PDF
            p.showPage()
            p.save()
            
            # FileResponse sets the Content-Disposition header so that browsers
            # present the option to save the file.
            buffer.seek(0)
            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="visitor_log_{year}_{month}.pdf"'
            response.write(buffer.getvalue())
            buffer.close()
            
            return response
    
    return redirect('accesslog:visitor_log')

@conditional_login_required
def get_visitor_info(request):
    name = request.GET.get('name')
    
    visitor = Visitor.objects.filter(
        visitor_name=name
    ).order_by('-date_of_visit').first()
    
    if visitor:
        return JsonResponse({
            'name': visitor.visitor_name,
            'company': visitor.visitor_company,
            'is_us_citizen': visitor.is_us_citizen,
        })
    return JsonResponse({})

@conditional_login_required
def get_staged_info(request, staged_id):
    staged = get_object_or_404(Staged, id=staged_id)
    return JsonResponse({
        'name': staged.visitor_name,
        'company': staged.visitor_company,
        'reason': staged.reason_for_visit,
    })