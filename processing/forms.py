import re
from decimal import Decimal, InvalidOperation
from django import forms
from django.forms import inlineformset_factory
from .models import ProcessContract, ProcessClin, ProcessClinSplit

_CLIN_SPLIT_KEY = re.compile(
    r"^clin-(?P<clin_id>\d+)-splits-(?:(?P<split_id>\d+)|new-(?P<new_idx>\d+))-"
    r"(?P<field>company_name|split_value|split_paid)$"
)


def parse_clin_split_keys(post_data):
    """Parse POST data into (clin_id) -> (ref_key) -> {field: value} where ref is split pk or 'new-idx'."""
    out = {}
    for key, raw in post_data.items():
        m = _CLIN_SPLIT_KEY.match(key)
        if not m:
            continue
        clin_id = m.group("clin_id")
        if m.group("split_id"):
            ref = m.group("split_id")
        else:
            ref = f"new-{m.group('new_idx')}"
        field = m.group("field")
        d = out.setdefault(clin_id, {})
        d.setdefault(ref, {})[field] = raw
    return out


def persist_clin_splits_for_contract(process_contract, post_data):
    """
    Create/update/delete ProcessClinSplit rows from clin-<id>-splits-... keys.
    Returns True if any DB write occurred.
    """
    groups = parse_clin_split_keys(post_data)
    if not groups:
        return False

    changed = False
    for clin_id, refs in groups.items():
        try:
            clin = ProcessClin.objects.get(pk=clin_id, process_contract=process_contract)
        except ProcessClin.DoesNotExist:
            continue

        kept_ids = [int(r) for r in refs if not r.startswith("new-")]
        dcount, _ = clin.splits.exclude(pk__in=kept_ids).delete()
        if dcount:
            changed = True

        for ref, fields in refs.items():
            if ref.startswith("new-"):
                company = (fields.get("company_name") or "").strip()
                if not company:
                    continue
                try:
                    sv = fields.get("split_value", "") or "0"
                    sp = fields.get("split_paid", "") or "0"
                    split_value = Decimal(str(sv).replace(",", "")) if str(sv).strip() else Decimal("0")
                    split_paid = Decimal(str(sp).replace(",", "")) if str(sp).strip() else Decimal("0")
                except (InvalidOperation, ValueError):
                    continue
                ProcessClinSplit.objects.create(
                    clin=clin,
                    company_name=company,
                    split_value=split_value,
                    split_paid=split_paid,
                )
                changed = True
            else:
                try:
                    row = clin.splits.get(pk=ref)
                except ProcessClinSplit.DoesNotExist:
                    continue
                if "company_name" in fields:
                    row.company_name = (fields["company_name"] or "").strip()
                for pkey in ("split_value", "split_paid"):
                    if pkey in fields and fields[pkey] is not None and str(fields[pkey]).strip() != "":
                        try:
                            setattr(row, pkey, Decimal(str(fields[pkey]).replace(",", "")))
                        except (InvalidOperation, ValueError):
                            pass
                row.save()
                changed = True
    return changed


class ProcessClinSplitForm(forms.ModelForm):
    class Meta:
        model = ProcessClinSplit
        fields = ['company_name', 'split_value', 'split_paid']

class ProcessContractForm(forms.ModelForm):
    class Meta:
        model = ProcessContract
        fields = [
            'idiq_contract',
            'contract_number',
            'solicitation_type',
            'po_number',
            'tab_num',
            'buyer',
            'buyer_text',
            'contract_type',
            'contract_type_text',
            'award_date',
            'due_date',
            'due_date_late',
            'sales_class',
            'sales_class_text',
            'nist',
            'files_url',
            'contract_value',
            'description',
            'planned_split',
            'plan_gross',
            'status'
        ]
        widgets = {
            'award_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
            'buyer_text': forms.TextInput(attrs={'class': 'buyer-text-input', 'readonly': True}),
            'contract_type_text': forms.TextInput(attrs={'readonly': True}),
            'sales_class_text': forms.TextInput(attrs={'readonly': True}),
            'files_url': forms.URLInput(attrs={'class': 'url-input'}),
            'due_date_late': forms.CheckboxInput(attrs={'class': 'checkbox-input'})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)

        if instance.contract_type:
            instance.contract_type_text = instance.contract_type.description
        if instance.sales_class:
            instance.sales_class_text = instance.sales_class.sales_team

        if commit:
            instance.save()
            if self.data:
                persist_clin_splits_for_contract(instance, self.data)

        return instance

class ProcessClinForm(forms.ModelForm):
    class Meta:
        model = ProcessClin
        fields = [
            'item_number',
            'item_type',
            'nsn',
            'nsn_text',
            'nsn_description_text',
            'supplier',
            'supplier_text',
            'order_qty',
            'unit_price',
            'item_value',
            'description',
            'ia',
            'fob',
            'po_num_ext',
            'tab_num',
            'clin_po_num',
            'po_number',
            'clin_type',
            'status',
            'due_date',
            'supplier_due_date',
            'price_per_unit',
            'quote_value'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 2}),
            'nsn_text': forms.TextInput(attrs={'class': 'nsn-text-input'}),
            'nsn_description_text': forms.TextInput(attrs={'class': 'nsn-desc-input'}),
            'supplier_text': forms.TextInput(attrs={'class': 'supplier-text-input'}),
            'order_qty': forms.NumberInput(attrs={'step': '1', 'class': 'qty-input'}),
            'unit_price': forms.NumberInput(attrs={'step': '0.01', 'class': 'price-input'}),
            'item_value': forms.NumberInput(attrs={'step': '0.01', 'class': 'value-input', 'readonly': True}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'supplier_due_date': forms.DateInput(attrs={'type': 'date'}),
            'price_per_unit': forms.NumberInput(attrs={'step': '0.01', 'class': 'price-input'}),
            'quote_value': forms.NumberInput(attrs={'step': '0.01', 'class': 'value-input', 'readonly': True})
        }

    def clean(self):
        cleaned_data = super().clean()
        order_qty = cleaned_data.get('order_qty')
        unit_price = cleaned_data.get('unit_price')
        price_per_unit = cleaned_data.get('price_per_unit')

        if order_qty and unit_price:
            cleaned_data['item_value'] = order_qty * unit_price

        if order_qty and price_per_unit:
            cleaned_data['quote_value'] = order_qty * price_per_unit

        return cleaned_data

ProcessClinFormSet = inlineformset_factory(
    ProcessContract,
    ProcessClin,
    fields=('item_number', 'item_type', 'nsn', 'supplier', 'order_qty', 'unit_price', 'item_value',
            'status', 'due_date', 'supplier_due_date', 'price_per_unit', 'quote_value', 'clin_po_num',
            'tab_num', 'uom', 'ia', 'fob'),
    extra=0,
    can_delete=True
)
