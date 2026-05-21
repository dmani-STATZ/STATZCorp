from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from STATZWeb.decorators import conditional_login_required
from docx import Document
import io
import logging

from ..models import AcknowledgementLetter, AcknowledgmentLetterTemplate, Clin
from ..forms import AcknowledgementLetterForm
from suppliers.models import Contact
from users.user_settings import UserSettings

logger = logging.getLogger('django')


def _get_or_create_acknowledgment_letter(clin, request):
    """Get or create an AcknowledgementLetter for a CLIN with prefill logic."""
    letter = AcknowledgementLetter.objects.filter(clin=clin).first()

    if not letter:
        letter = AcknowledgementLetter(clin=clin)

        if clin.supplier:
            supplier = clin.supplier
            letter.supplier = supplier.name

            contact = Contact.objects.filter(supplier=supplier, is_primary=True).first()
            if contact:
                letter.salutation = contact.salutation
                if contact.name:
                    names = contact.name.split(maxsplit=1)
                    letter.addr_fname = names[0]
                    letter.addr_lname = names[1] if len(names) > 1 else ''

            if supplier.physical_address:
                addr = supplier.physical_address
                letter.st_address = addr.address_line_1
                letter.city = addr.city
                letter.state = addr.state
                letter.zip = addr.zip

        letter.po = clin.po_number
        letter.po_ext = clin.po_num_ext
        letter.contract_num = clin.contract.contract_number if clin.contract else None
        letter.supplier_due_date = clin.supplier_due_date

        fat_plt_clin = Clin.objects.filter(
            contract=clin.contract,
            item_type__in=['G', 'C', 'L']
        ).first()
        if fat_plt_clin:
            letter.fat_due_date = fat_plt_clin.supplier_due_date

        letter.statz_contact = f"{request.user.first_name} {request.user.last_name}".strip()
        letter.statz_contact_email = request.user.email

        user_settings = UserSettings.get_multiple_settings(request.user, [
            'statz_contact_title',
            'statz_contact_phone'
        ])
        letter.statz_contact_title = user_settings.get('statz_contact_title', 'Contract Manager')
        letter.statz_contact_phone = user_settings.get('statz_contact_phone', '')
        letter.letter_date = timezone.now().date()
        letter.save()

    return letter


@conditional_login_required
def get_acknowledgment_letter(request, clin_id):
    """Get or create an acknowledgment letter for a CLIN (modal JSON API)."""
    clin = get_object_or_404(Clin, id=clin_id)
    letter = _get_or_create_acknowledgment_letter(clin, request)
    form = AcknowledgementLetterForm(instance=letter)

    return JsonResponse({
        'success': True,
        'html': render(request, 'contracts/partials/acknowledgment_letter_form.html', {
            'form': form,
            'clin': clin,
            'letter': letter
        }).content.decode('utf-8')
    })


@conditional_login_required
def acknowledgment_letter_page(request, clin_id):
    """Dedicated full-page editor for the PO acknowledgment letter."""
    clin = get_object_or_404(
        Clin.objects.select_related('contract', 'supplier', 'supplier__physical_address'),
        id=clin_id,
    )
    letter = _get_or_create_acknowledgment_letter(clin, request)
    form = AcknowledgementLetterForm(instance=letter)

    return render(request, 'contracts/acknowledgment_letter_page.html', {
        'letter': letter,
        'form': form,
        'clin': clin,
        'contract': clin.contract,
        'active_template': AcknowledgmentLetterTemplate.get_active(),
        'user_is_staff': request.user.is_staff,
    })


def _docx_to_html(doc):
    """
    Convert a python-docx Document to an HTML string for preview.
    Preserves: run-level color, bold, italic, paragraph alignment,
    Heading 1 style, and table structure.
    Ignores images (intentional).
    """
    from docx.oxml.ns import qn
    import html as _html

    def get_run_html(run, inherited_bold=False):
        text = run.text
        if not text:
            return ''

        # Escape HTML entities
        text = _html.escape(text).replace('\n', '<br>')

        rPr = run._element.find(qn('w:rPr'))
        color = None
        bold = inherited_bold
        italic = run.italic or False

        if rPr is not None:
            # Run-level color
            color_el = rPr.find(qn('w:color'))
            if color_el is not None:
                val = color_el.get(qn('w:val'), '')
                if val and val.upper() not in ('000000', 'AUTO'):
                    color = val

            # Run-level bold (explicit)
            bold_el = rPr.find(qn('w:b'))
            if bold_el is not None:
                bold = True

            # Run-level italic (explicit)
            italic_el = rPr.find(qn('w:i'))
            if italic_el is not None:
                italic = True

        # Build span style
        span_style = ''
        if color:
            span_style += f'color:#{color};'

        if span_style:
            text = f'<span style="{span_style}">{text}</span>'
        if bold:
            text = f'<strong>{text}</strong>'
        if italic:
            text = f'<em>{text}</em>'

        return text

    def get_para_html(para):
        style = para.style.name

        # Alignment
        pPr = para._element.find(qn('w:pPr'))
        align = 'left'
        if pPr is not None:
            jc = pPr.find(qn('w:jc'))
            if jc is not None:
                align = jc.get(qn('w:val'), 'left')

        # Empty paragraph → spacer
        if not para.text.strip():
            return '<p class="docx-empty"></p>'

        # Determine class and inherited bold
        if style == 'Heading 1':
            css_class = 'docx-h1-center' if align == 'center' else 'docx-h1'
            inherited_bold = True
        else:
            css_class = 'docx-normal'
            inherited_bold = False

        # Build run HTML
        runs_html = ''.join(
            get_run_html(run, inherited_bold) for run in para.runs
        )

        style_attr = f' style="text-align:{align};"' if align != 'left' else ''
        return f'<p class="{css_class}"{style_attr}>{runs_html}</p>'

    def get_table_html(table):
        rows_html = ''
        for row in table.rows:
            cells_html = ''
            seen_tcs = set()
            for cell in row.cells:
                # Skip duplicate cell objects (python-docx repeats merged cells)
                if id(cell._tc) in seen_tcs:
                    continue
                seen_tcs.add(id(cell._tc))

                # Determine colspan from w:gridSpan
                colspan = 1
                tcPr = cell._tc.find(qn('w:tcPr'))
                if tcPr is not None:
                    gridSpan = tcPr.find(qn('w:gridSpan'))
                    if gridSpan is not None:
                        try:
                            colspan = int(gridSpan.get(qn('w:val'), 1))
                        except (ValueError, TypeError):
                            colspan = 1

                cell_content = ''.join(
                    get_para_html(p) for p in cell.paragraphs
                )
                colspan_attr = f' colspan="{colspan}"' if colspan > 1 else ''
                cells_html += f'<td{colspan_attr}>{cell_content}</td>'

            rows_html += f'<tr>{cells_html}</tr>'
        return f'<table class="docx-table"><tbody>{rows_html}</tbody></table>'

    # Iterate document body elements in order
    parts = []
    body = doc.element.body

    para_index = 0
    table_index = 0

    for child in body:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == 'p':
            if para_index < len(doc.paragraphs):
                parts.append(get_para_html(doc.paragraphs[para_index]))
            para_index += 1
        elif tag == 'tbl':
            if table_index < len(doc.tables):
                parts.append(get_table_html(doc.tables[table_index]))
            table_index += 1

    return '\n'.join(parts)


@conditional_login_required
def preview_acknowledgment_letter(request, letter_id):
    """
    Render the active .docx template with placeholder substitution applied,
    converted to HTML via _docx_to_html. The preview reflects the actual
    uploaded ISO document — no hardcoded HTML.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required.'})

    active_template = AcknowledgmentLetterTemplate.get_active()
    if not active_template:
        return JsonResponse({
            'success': False,
            'error': 'No active letter template. Ask a staff member to upload one.'
        })

    post = request.POST

    salutation = post.get('salutation', '').strip()
    fname = post.get('addr_fname', '').strip()
    lname = post.get('addr_lname', '').strip()
    recipient_name = f"{salutation} {fname} {lname}".strip()

    city = post.get('city', '').strip()
    state = post.get('state', '').strip()
    zip_ = post.get('zip', '').strip()
    city_state_zip = f"{city}, {state} {zip_}".strip().strip(',')

    po = post.get('po', '').strip()
    po_ext = post.get('po_ext', '').strip()
    po_number = f"{po}{f' / {po_ext}' if po_ext else ''}"

    def fmt_date(val):
        if not val:
            return ''
        try:
            from datetime import datetime
            return datetime.strptime(val, '%Y-%m-%d').strftime('%B %d, %Y')
        except ValueError:
            return val

    substitutions = {
        '{{LETTER_DATE}}':       fmt_date(post.get('letter_date', '')),
        '{{RECIPIENT_NAME}}':    recipient_name,
        '{{SUPPLIER_NAME}}':     post.get('supplier', '').replace(' ', '\u00A0'),
        '{{STREET_ADDRESS}}':    post.get('st_address', ''),
        '{{CITY_STATE_ZIP}}':    city_state_zip,
        '{{PO_NUMBER}}':         po_number,
        '{{CONTRACT_NUMBER}}':   post.get('contract_num', ''),
        '{{SUPPLIER_DUE_DATE}}': fmt_date(post.get('supplier_due_date', '')),
        '{{FAT_DUE_DATE}}':      fmt_date(post.get('fat_due_date', '')),
        '{{PLT_DUE_DATE}}':      fmt_date(post.get('plt_due_date', '')),
        '{{DPAS_PRIORITY}}':     post.get('dpas_priority', ''),
        '{{STATZ_CONTACT}}':     post.get('statz_contact', ''),
        '{{STATZ_TITLE}}':       post.get('statz_contact_title', ''),
        '{{STATZ_PHONE}}':       post.get('statz_contact_phone', ''),
        '{{STATZ_EMAIL}}':       post.get('statz_contact_email', ''),
    }

    try:
        doc = Document(active_template.file.path)
    except Exception as e:
        logger.error(f"Preview: could not open template: {e}")
        return JsonResponse({'success': False, 'error': 'Could not open template file.'})

    def replace_in_doc(doc, placeholder, value):
        """
        Replace placeholder text in all paragraphs and table cells.
        Handles placeholders split across multiple runs by consolidating
        run text at the paragraph level before substitution.
        """
        text = str(value) if value is not None else ''

        def replace_in_paragraph(para):
            # Fast exit if placeholder not present anywhere in paragraph
            if placeholder not in para.text:
                return
            # Consolidate all run text into the first run, clear the rest.
            # This handles placeholders split across multiple runs by Word.
            full_text = ''.join(run.text for run in para.runs)
            if placeholder not in full_text:
                return
            if para.runs:
                para.runs[0].text = full_text.replace(placeholder, text)
                for run in para.runs[1:]:
                    run.text = ''

        for para in doc.paragraphs:
            replace_in_paragraph(para)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        replace_in_paragraph(para)

    for placeholder, value in substitutions.items():
        replace_in_doc(doc, placeholder, value)

    try:
        html = _docx_to_html(doc)
    except Exception as e:
        logger.error(f"Preview: docx-to-HTML conversion failed: {e}")
        return JsonResponse({'success': False, 'error': 'Could not render preview.'})

    return JsonResponse({'success': True, 'html': html})


@conditional_login_required
def upload_acknowledgment_template(request):
    """Staff-only upload of a new .docx letter template (auto-activates)."""
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': 'Staff access required.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'})

    template_file = request.FILES.get('template_file')
    rev_number = (request.POST.get('rev_number') or '').strip()

    if not template_file:
        return JsonResponse({'success': False, 'error': 'No file uploaded.'})
    if not rev_number:
        return JsonResponse({'success': False, 'error': 'Revision number is required.'})

    name_lower = template_file.name.lower()
    if not name_lower.endswith('.docx'):
        return JsonResponse({'success': False, 'error': 'File must be a .docx document.'})

    template = AcknowledgmentLetterTemplate(
        file=template_file,
        rev_number=rev_number,
        uploaded_by=request.user,
    )
    template.save()
    template.activate()

    uploaded_by = request.user.get_full_name() or request.user.username
    return JsonResponse({
        'success': True,
        'rev_number': template.rev_number,
        'uploaded_by': uploaded_by,
        'uploaded_at': template.uploaded_at.strftime('%B %d, %Y'),
        'download_url': template.file.url,
    })


@conditional_login_required
def update_acknowledgment_letter(request, letter_id):
    """Update an existing acknowledgment letter."""
    letter = get_object_or_404(AcknowledgementLetter, id=letter_id)

    if request.method == 'POST':
        form = AcknowledgementLetterForm(request.POST, instance=letter)
        if form.is_valid():
            letter = form.save()

            statz_contact_title = form.cleaned_data.get('statz_contact_title')
            statz_contact_phone = form.cleaned_data.get('statz_contact_phone')

            if statz_contact_title:
                UserSettings.save_setting(
                    user=request.user,
                    name='statz_contact_title',
                    value=statz_contact_title,
                    setting_type='string',
                    description='User contact title for acknowledgment letters'
                )

            if statz_contact_phone:
                UserSettings.save_setting(
                    user=request.user,
                    name='statz_contact_phone',
                    value=statz_contact_phone,
                    setting_type='string',
                    description='User contact phone for acknowledgment letters'
                )

            return JsonResponse({'success': True})
        return JsonResponse({
            'success': False,
            'errors': form.errors
        })

    return JsonResponse({'success': False, 'error': 'Invalid request method'})


@conditional_login_required
def generate_acknowledgment_letter_doc(request, letter_id):
    """Generate and download a Word document for an acknowledgment letter."""
    letter = get_object_or_404(AcknowledgementLetter, id=letter_id)

    if request.method == 'POST':
        if any(name in request.POST for name in AcknowledgementLetterForm().fields):
            form = AcknowledgementLetterForm(request.POST, instance=letter)
            if form.is_valid():
                letter = form.save()
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid form data',
                    'errors': form.errors,
                })

    active_template = AcknowledgmentLetterTemplate.get_active()
    if not active_template:
        return JsonResponse({
            'success': False,
            'error': 'No active letter template. Ask a staff member to upload one.',
        })

    try:
        doc = Document(active_template.file.path)
    except Exception as e:
        logger.error(f"Error opening acknowledgment letter template: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Could not open letter template.',
        })

    doc.core_properties.author = request.user.get_full_name() or request.user.username
    doc.core_properties.title = f"Purchase Order Acknowledgment Letter - {letter.po or ''}"

    def replace_placeholder(doc, placeholder, value):
        """
        Replace placeholder text in all paragraphs and table cells.
        Handles placeholders split across multiple runs by consolidating
        run text at the paragraph level before substitution.
        """
        text = str(value) if value is not None else ''

        def replace_in_paragraph(para):
            # Fast exit if placeholder not present anywhere in paragraph
            if placeholder not in para.text:
                return
            # Consolidate all run text into the first run, clear the rest.
            # This handles placeholders split across multiple runs by Word.
            full_text = ''.join(run.text for run in para.runs)
            if placeholder not in full_text:
                return
            if para.runs:
                para.runs[0].text = full_text.replace(placeholder, text)
                for run in para.runs[1:]:
                    run.text = ''

        for para in doc.paragraphs:
            replace_in_paragraph(para)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        replace_in_paragraph(para)

    replace_placeholder(doc, '{{LETTER_DATE}}',
        letter.letter_date.strftime('%B %d, %Y') if letter.letter_date else timezone.now().date().strftime('%B %d, %Y'))

    full_name = f"{letter.salutation or ''} {letter.addr_fname or ''} {letter.addr_lname or ''}".strip()
    replace_placeholder(doc, '{{RECIPIENT_NAME}}', full_name)
    replace_placeholder(doc, '{{SUPPLIER_NAME}}', (letter.supplier or '').replace(' ', '\u00A0'))
    replace_placeholder(doc, '{{STREET_ADDRESS}}', letter.st_address or '')
    replace_placeholder(doc, '{{CITY_STATE_ZIP}}',
        f"{letter.city or ''}, {letter.state or ''} {letter.zip or ''}".strip().strip(','))

    po_number = f"{letter.po or ''}{f' / {letter.po_ext}' if letter.po_ext else ''}"
    replace_placeholder(doc, '{{PO_NUMBER}}', po_number)
    replace_placeholder(doc, '{{CONTRACT_NUMBER}}', letter.contract_num or '')

    replace_placeholder(doc, '{{SUPPLIER_DUE_DATE}}',
        letter.supplier_due_date.strftime('%B %d, %Y') if letter.supplier_due_date else 'N/A')
    replace_placeholder(doc, '{{FAT_DUE_DATE}}',
        letter.fat_due_date.strftime('%B %d, %Y') if letter.fat_due_date else 'N/A')
    replace_placeholder(doc, '{{PLT_DUE_DATE}}',
        letter.plt_due_date.strftime('%B %d, %Y') if letter.plt_due_date else 'N/A')
    replace_placeholder(doc, '{{DPAS_PRIORITY}}', letter.dpas_priority or '')

    replace_placeholder(doc, '{{STATZ_CONTACT}}',
        letter.statz_contact or request.user.get_full_name() or request.user.username)
    replace_placeholder(doc, '{{STATZ_TITLE}}', letter.statz_contact_title or 'Contract Manager')
    replace_placeholder(doc, '{{STATZ_PHONE}}', letter.statz_contact_phone or '')
    replace_placeholder(doc, '{{STATZ_EMAIL}}',
        letter.statz_contact_email or request.user.email)

    try:
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        po_slug = (letter.po or 'letter').replace('/', '-').replace(' ', '_')
        file_name = f"PO_Acknowledgment_{po_slug}_{timezone.now().date().strftime('%Y%m%d')}.docx"

        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        response['Content-Disposition'] = f'attachment; filename="{file_name}"'
        return response

    except Exception as e:
        logger.error(f"Error generating acknowledgment letter document: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Error generating document. Please try again.',
        })
