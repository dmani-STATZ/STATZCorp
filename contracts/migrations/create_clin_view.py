from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('contracts', '0032_update_reminder_note_relationship'),  # Update this to your latest migration
    ]

    operations = [
        migrations.RunSQL(
            # SQL to create the view
            """
            CREATE OR ALTER VIEW clin_view AS
            SELECT 
                c.id,
                c.contract_id,
                con.contract_number,
                c.clin_po_num,
                c.po_number,
                c.po_num_ext,
                c.tab_num,
                c.sub_contract,
                
                c.clin_type_id,
                ct.description AS clin_type_description,
                
                c.supplier_id,
                s.name AS supplier_name,
                s.cage_code AS supplier_cage_code,
                
                c.nsn_id,
                n.nsn_code,
                n.description AS nsn_description,
                
                c.ia,
                c.fob,
                c.order_qty,
                c.ship_qty,
                
                c.due_date,
                c.due_date_late,
                c.supplier_due_date,
                c.supplier_due_date_late,
                c.ship_date,
                c.ship_date_late,
                
                c.special_payment_terms_id,
                spt.code AS special_payment_terms_code,
                spt.terms AS special_payment_terms_description,
                c.special_payment_terms_paid,
                
                c.contract_value,
                c.po_amount,
                c.paid_amount,
                
                c.created_by_id,
                cb.username AS created_by_username,
                c.created_on,
                c.modified_by_id,
                mb.username AS modified_by_username,
                c.modified_on
            FROM 
                contracts_clin c
            LEFT JOIN 
                contracts_contract con ON c.contract_id = con.id
            LEFT JOIN 
                contracts_clintype ct ON c.clin_type_id = ct.id
            LEFT JOIN 
                contracts_supplier s ON c.supplier_id = s.id
            LEFT JOIN 
                contracts_nsn n ON c.nsn_id = n.id
            LEFT JOIN 
                contracts_specialpaymentterms spt ON c.special_payment_terms_id = spt.id
            LEFT JOIN 
                auth_user cb ON c.created_by_id = cb.id
            LEFT JOIN 
                auth_user mb ON c.modified_by_id = mb.id
            """,
            
            # SQL to drop the view (for reversing the migration)
            "DROP VIEW IF EXISTS clin_view"
        )
    ] 