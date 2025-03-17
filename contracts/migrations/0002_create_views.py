from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('contracts', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            # Create CLIN View
            """
            CREATE VIEW clin_view AS
            SELECT 
                c.id,
                c.contract_id,
                c.item_number,
                c.item_type,
                c.item_value,
                cont.contract_number,
                c.clin_po_num,
                c.po_number,
                c.po_num_ext,
                c.tab_num,
                
                ct.id as clin_type_id,
                ct.description as clin_type_description,
                
                s.id as supplier_id,
                s.name as supplier_name,
                s.cage_code as supplier_cage_code,
                
                n.id as nsn_id,
                n.nsn_code,
                n.description as nsn_description,
                
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
                
                spt.id as special_payment_terms_id,
                spt.code as special_payment_terms_code,
                spt.terms as special_payment_terms_description,
                c.special_payment_terms_paid,
                
                c.clin_value,
                c.paid_amount,
                
                c.created_by_id,
                cu.username as created_by_username,
                c.created_on,
                c.modified_by_id,
                mu.username as modified_by_username,
                c.modified_on
            FROM contracts_clin c
            LEFT JOIN contracts_contract cont ON c.contract_id = cont.id
            LEFT JOIN contracts_clintype ct ON c.clin_type_id = ct.id
            LEFT JOIN contracts_supplier s ON c.supplier_id = s.id
            LEFT JOIN contracts_nsn n ON c.nsn_id = n.id
            LEFT JOIN contracts_specialpaymentterms spt ON c.special_payment_terms_id = spt.id
            LEFT JOIN auth_user cu ON c.created_by_id = cu.id
            LEFT JOIN auth_user mu ON c.modified_by_id = mu.id;
            """,
            # Drop CLIN View
            "DROP VIEW IF EXISTS clin_view;"
        ),
        migrations.RunSQL(
            # Create NSN View
            """
            CREATE VIEW nsn_view AS
            SELECT 
                n.id,
                n.nsn_code,
                n.description,
                n.part_number,
                n.revision,
                n.notes,
                n.directory_url,
                COUNT(c.id) as clin_count,
                CONCAT(
                    COALESCE(n.nsn_code, ''),
                    ' ',
                    COALESCE(n.description, ''),
                    ' ',
                    COALESCE(n.part_number, ''),
                    ' ',
                    COALESCE(n.revision, ''),
                    ' ',
                    COALESCE(n.notes, '')
                ) as search_vector
            FROM contracts_nsn n
            LEFT JOIN contracts_clin c ON n.id = c.nsn_id
            GROUP BY n.id, n.nsn_code, n.description, n.part_number, n.revision, n.notes, n.directory_url;
            """,
            # Drop NSN View
            "DROP VIEW IF EXISTS nsn_view;"
        ),
    ] 