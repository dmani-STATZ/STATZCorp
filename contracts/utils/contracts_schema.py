from django.apps import apps
from django.db import models
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
import re

def generate_contracts_schema_description():
    """
    Dynamically generates a text description of the database schema
    specifically for models in the 'contracts' Django app, with hand-curated FK relationships.
    """
    schema_description = "DATABASE SCHEMA FOR CONTRACTS APP:\n\n"
    
    try:
        contracts_app_config = apps.get_app_config('contracts')
        contracts_models = contracts_app_config.get_models()
    except LookupError:
        return "Error: 'contracts' app not found. Please ensure it's registered in INSTALLED_APPS."

    # --- FIRST PASS: GENERATE TABLE AND COLUMN DESCRIPTIONS ---
    for model in contracts_models:
        table_name = model._meta.db_table 
        schema_description += f"Table: {table_name}\n"
        schema_description += "Columns:\n"

        # Iterate over all concrete fields (actual columns in the DB table)
        for field in model._meta.concrete_fields:
            field_name = field.column # Get the actual column name in the DB

            field_type = type(field).__name__
            
            # Basic type mapping
            db_type_hint = ""
            if isinstance(field, models.CharField) or isinstance(field, models.TextField):
                db_type_hint = "TEXT"
            elif isinstance(field, models.IntegerField) or isinstance(field, models.AutoField) or isinstance(field, models.PositiveIntegerField):
                db_type_hint = "INTEGER"
            elif isinstance(field, models.DecimalField):
                db_type_hint = f"DECIMAL({field.max_digits},{field.decimal_places})" 
            elif isinstance(field, models.FloatField):
                db_type_hint = "REAL" # or FLOAT
            elif isinstance(field, models.DateField):
                db_type_hint = "DATE"
            elif isinstance(field, models.DateTimeField):
                db_type_hint = "DATETIME"
            elif isinstance(field, models.BooleanField):
                db_type_hint = "BOOLEAN"
            elif isinstance(field, (models.ForeignKey, models.OneToOneField)):
                db_type_hint = "INTEGER" # FKs store an integer ID
            elif isinstance(field, models.JSONField):
                db_type_hint = "JSON"
            else:
                db_type_hint = "UNKNOWN" 

            description_parts = [f"- {field_name} ({db_type_hint})"]

            if field.primary_key:
                description_parts.append("Primary Key")
            if field.unique and not field.primary_key: 
                description_parts.append("UNIQUE")
            if not field.null and not field.primary_key: 
                 description_parts.append("NOT NULL")

            schema_description += f"  {' '.join(description_parts)}\n"
        schema_description += "\n"

    # --- HAND-CURATED RELATIONSHIPS SECTION ---
    # This section is manually defined based on your models.py
    # You can choose to be more or less exhaustive based on common query patterns.
    schema_description += "Relationships:\n"
    schema_description += "- contracts_contract.idiq_contract_id (FK) refers to contracts_idiqcontract.id\n"
    schema_description += "- contracts_contract.status_id (FK) refers to contracts_contractstatus.id\n"
    schema_description += "- contracts_contract.canceled_reason_id (FK) refers to contracts_canceledreason.id\n"
    schema_description += "- contracts_contract.buyer_id (FK) refers to contracts_buyer.id\n"
    schema_description += "- contracts_contract.contract_type_id (FK) refers to contracts_contracttype.id\n"
    schema_description += "- contracts_contract.sales_class_id (FK) refers to contracts_salesclass.id\n"
    schema_description += "- contracts_contract.created_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_contract.modified_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_contract.assigned_user_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_contract.reviewed_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_contract.notes (Generic Relation: use contracts_note.content_type_id and contracts_note.object_id with django_content_type.id)\n"
    schema_description += "- contracts_contract.payment_history (Generic Relation: use contracts_paymenthistory.content_type_id and contracts_paymenthistory.object_id with django_content_type.id)\n"
    schema_description += "- contracts_contractsplit.contract_id (FK) refers to contracts_contract.id\n"

    schema_description += "- contracts_clin.contract_id (FK) refers to contracts_contract.id\n"
    schema_description += "- contracts_clin.clin_type_id (FK) refers to contracts_clintype.id\n"
    schema_description += "- contracts_clin.supplier_id (FK) refers to contracts_supplier.id\n"
    schema_description += "- contracts_clin.nsn_id (FK) refers to contracts_nsn.id\n"
    schema_description += "- contracts_clin.special_payment_terms_id (FK) refers to contracts_specialpaymentterms.id\n"
    schema_description += "- contracts_clin.created_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_clin.modified_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_clin.notes (Generic Relation: use contracts_note.content_type_id and contracts_note.object_id with django_content_type.id)\n"
    schema_description += "- contracts_clin.payment_history (Generic Relation: use contracts_paymenthistory.content_type_id and contracts_paymenthistory.object_id with django_content_type.id\n"
    schema_description += "- contracts_clinshipment.clin_id (FK) refers to contracts_clin.id\n"

    schema_description += "- contracts_paymenthistory.content_type_id (FK) refers to django_content_type.id\n"
    schema_description += "- contracts_paymenthistory.created_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_paymenthistory.modified_by_id (FK) refers to auth_user.id\n"

    schema_description += "- contracts_idiqcontract.buyer_id (FK) refers to contracts_buyer.id\n"
    schema_description += "- contracts_idiqcontract.created_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_idiqcontract.modified_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_idiqcontractdetails.idiq_contract_id (FK) refers to contracts_idiqcontract.id\n"
    schema_description += "- contracts_idiqcontractdetails.nsn_id (FK) refers to contracts_nsn.id\n"
    schema_description += "- contracts_idiqcontractdetails.supplier_id (FK) refers to contracts_supplier.id\n"

    schema_description += "- contracts_supplier.supplier_type_id (FK) refers to contracts_suppliertype.id\n"
    schema_description += "- contracts_supplier.billing_address_id (FK) refers to contracts_address.id\n"
    schema_description += "- contracts_supplier.shipping_address_id (FK) refers to contracts_address.id\n"
    schema_description += "- contracts_supplier.physical_address_id (FK) refers to contracts_address.id\n"
    schema_description += "- contracts_supplier.contact_id (FK) refers to contracts_contact.id\n"
    schema_description += "- contracts_supplier.probation_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_supplier.conditional_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_supplier.special_terms_id (FK) refers to contracts_specialpaymentterms.id\n"
    schema_description += "- contracts_supplier.packhouse_id (FK) refers to contracts_supplier.id (Self-referencing FK)\n"
    schema_description += "- contracts_supplier.created_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_supplier.modified_by_id (FK) refers to auth_user.id\n"

    schema_description += "- contracts_buyer.address_id (FK) refers to contracts_address.id\n"

    schema_description += "- contracts_note.content_type_id (FK) refers to django_content_type.id\n"
    schema_description += "- contracts_note.created_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_note.modified_by_id (FK) refers to auth_user.id\n"

    schema_description += "- contracts_acknowledgementletter.clin_id (FK) refers to contracts_clin.id\n"
    schema_description += "- contracts_acknowledgementletter.created_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_acknowledgementletter.modified_by_id (FK) refers to auth_user.id\n"

    schema_description += "- contracts_clinacknowledgment.clin_id (FK) refers to contracts_clin.id\n"
    schema_description += "- contracts_clinacknowledgment.po_to_supplier_user_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_clinacknowledgment.clin_reply_user_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_clinacknowledgment.po_to_qar_user_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_clinacknowledgment.created_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_clinacknowledgment.modified_by_id (FK) refers to auth_user.id\n"

    schema_description += "- contracts_contact.address_id (FK) refers to contracts_address.id\n"

    schema_description += "- contracts_suppliercertification.supplier_id (FK) refers to contracts_supplier.id\n"
    schema_description += "- contracts_suppliercertification.certification_type_id (FK) refers to contracts_certificationtype.id\n"

    schema_description += "- contracts_supplierclassification.supplier_id (FK) refers to contracts_supplier.id\n"
    schema_description += "- contracts_supplierclassification.classification_type_id (FK) refers to contracts_classificationtype.id\n"

    schema_description += "- contracts_reminder.reminder_user_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_reminder.reminder_completed_user_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_reminder.note_id (FK) refers to contracts_note.id\n"

    schema_description += "- contracts_expedite.contract_id (FK) refers to contracts_contract.id\n"
    schema_description += "- contracts_expedite.initiatedby_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_expedite.successfulby_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_expedite.usedby_id (FK) refers to auth_user.id\n"

    schema_description += "- contracts_foldertracking.contract_id (FK) refers to contracts_contract.id\n"
    schema_description += "- contracts_foldertracking.added_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_foldertracking.closed_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_foldertracking.created_by_id (FK) refers to auth_user.id\n"
    schema_description += "- contracts_foldertracking.modified_by_id (FK) refers to auth_user.id\n"

    # Add instructions for GenericForeignKeys and AuditModel FKs here:
    schema_description += "\nNOTE on Generic Relations: For tables like contracts_note and contracts_paymenthistory, the `content_type_id` column is a foreign key to the `django_content_type` table, and `object_id` is the primary key of the related object (e.g., contracts_contract.id or contracts_clin.id). To join or filter by the related object, you typically join with `django_content_type` to find the correct `content_type_id` for your target model (`app_label='contracts', model='contract'` or `model='clin'`) and then use `object_id` to link to the target table's primary key.\n"
    schema_description += "NOTE on AuditModel Fields: `created_by_id` and `modified_by_id` columns in many tables (e.g., contracts_contract, contracts_clin) are foreign keys to the `auth_user` table (Django's User model).\n"

    schema_description += "\nInstructions:\n"
    schema_description += "- Use standard SQL (e.g., SELECT, FROM, JOIN, WHERE, GROUP BY, ORDER BY, LIMIT).\n"
    schema_description += "- When asked for dates, consider relevant date columns (e.g., created_on, modified_on, due_date, ship_date, award_date, payment_date).\n"
    schema_description += "- Use appropriate aggregate functions like SUM, AVG, COUNT, MIN, MAX.\n"
    schema_description += "- Ensure all column names and table names match the schema exactly. Pay close attention to singular/plural table names derived from Django models (e.g., 'contracts_contract', 'contracts_clin').\n"
    schema_description += "- If a query involves multiple tables, use JOIN clauses on the specified foreign key relationships (e.g., 'contracts_clin.contract_id = contracts_contract.id').\n"
    schema_description += "- When a user asks for supplier information and contract information, link the supplier to the contracts_clin then to the contracts_contract table to get the supplier information, only use the idiq tables when the user asks specificly idiq information\n"
    schema_description += "- For queries involving Users (e.g., created_by, modified_by, assigned_user, reviewed_by), join with the 'auth_user' table on the respective 'user_id = auth_user.id' column. The 'auth_user' table has 'id', 'username', 'first_name', 'last_name' columns.\n"
    schema_description += "- For generic relations (e.g., Note, PaymentHistory), filter on the 'content_type_id' column in that table by looking up the ID for the target model in the 'django_content_type' table. The 'django_content_type' table has 'id', 'app_label', 'model' columns. Then join using 'object_id' to the related object's 'id'.\n"
    schema_description += "- When referring to the primary key 'id' column for any table, it's typically just 'id'.\n"
    schema_description += "- If the user asks for a specific contract by ID, use the 'id' column in 'contracts_contract'.\n"
    schema_description += "- If the user asks for a specific contract by PO Number, use the 'po_number' column in 'contracts_contract' or 'contracts_clin'.\n"
    schema_description += "- Be mindful of null values when aggregating or filtering (e.g., use COALESCE for sums, IS NOT NULL for filtering).\n"
    schema_description += "- Prioritize explicit column names and table names from the schema.\n"

    return schema_description

def generate_condensed_contracts_schema(user_query=None, verbosity="minimal"):
    """
    Generate a condensed schema for the contracts app.
    - user_query: (optional) a string containing the user's question; will try to infer relevant tables/fields
    - verbosity: "minimal", "normal", or "full"
    """
    try:
        contracts_app_config = apps.get_app_config('contracts')
        contracts_models = list(contracts_app_config.get_models())
    except LookupError:
        return "Error: 'contracts' app not found. Please ensure it's registered in INSTALLED_APPS."

    # --- Infer needed tables from user_query ---
    needed_tables = set()
    needed_fields = set()
    if user_query:
        # Find all table and field names mentioned in the query (case-insensitive, underscores or camelCase)
        # Collect all possible table and field names from models
        table_names = {model._meta.db_table for model in contracts_models}
        field_names = set()
        model_fields = {}
        for model in contracts_models:
            model_fields[model._meta.db_table] = [f.column for f in model._meta.concrete_fields]
            field_names.update(model_fields[model._meta.db_table])
        # Search for table names in the query
        for tname in table_names:
            if re.search(rf"\b{re.escape(tname)}\b", user_query, re.IGNORECASE):
                needed_tables.add(tname)
        # Search for field names in the query
        for fname in field_names:
            if re.search(rf"\b{re.escape(fname)}\b", user_query, re.IGNORECASE):
                needed_fields.add(fname)
        # Add tables that have needed fields
        for tname, fnames in model_fields.items():
            if any(f in needed_fields for f in fnames):
                needed_tables.add(tname)
    # If nothing found, default to all tables
    if not needed_tables:
        needed_tables = {model._meta.db_table for model in contracts_models}

    # --- Generate schema description ---
    lines = []
    for model in contracts_models:
        table = model._meta.db_table
        if table not in needed_tables:
            continue
        if verbosity == "minimal":
            # One line per table: table: col1 (type), col2 (type, FK), ...
            col_desc = []
            for field in model._meta.concrete_fields:
                # Skip id if it's a standard PK
                if field.primary_key and field.column == "id":
                    continue
                ftype = type(field).__name__
                is_fk = isinstance(field, (models.ForeignKey, models.OneToOneField))
                desc = f"{field.column} ({ftype}{', FK' if is_fk else ''})"
                col_desc.append(desc)
            lines.append(f"{table}: id (PK), " + ", ".join(col_desc))
        elif verbosity == "normal":
            lines.append(f"Table: {table}")
            for field in model._meta.concrete_fields:
                ftype = type(field).__name__
                is_fk = isinstance(field, (models.ForeignKey, models.OneToOneField))
                desc = f"  - {field.column} ({ftype}{', FK' if is_fk else ''})"
                if field.primary_key:
                    desc += " [PK]"
                if field.unique and not field.primary_key:
                    desc += " [UNIQUE]"
                if not field.null and not field.primary_key:
                    desc += " [NOT NULL]"
                lines.append(desc)
            lines.append("")
        else:  # full
            lines.append(f"Table: {table}")
            for field in model._meta.concrete_fields:
                ftype = type(field).__name__
                is_fk = isinstance(field, (models.ForeignKey, models.OneToOneField))
                desc = f"  - {field.column} ({ftype}{', FK' if is_fk else ''})"
                if field.primary_key:
                    desc += " [PK]"
                if field.unique and not field.primary_key:
                    desc += " [UNIQUE]"
                if not field.null and not field.primary_key:
                    desc += " [NOT NULL]"
                if hasattr(field, 'related_model') and field.related_model:
                    desc += f" → {field.related_model._meta.db_table}(id)"
                lines.append(desc)
            lines.append("")
    # Add a summary if minimal
    if verbosity == "minimal":
        lines.append("\n[Only tables/fields inferred from the user query are included.]")
    return "\n".join(lines)