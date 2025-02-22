"""fix_booking_table

Revision ID: 3bcac961ce38
Revises: update_qr_barcode_columns
Create Date: 2025-02-22 17:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '3bcac961ce38'
down_revision = 'update_qr_barcode_columns'
branch_labels = None
depends_on = None

def upgrade():
    # Execute raw SQL commands
    commands = [
        # Update nullable columns with default values
        """
        DO $$
        BEGIN
            -- Update tier_id
            UPDATE booking SET tier_id = 'default_tier' WHERE tier_id IS NULL;
            
            -- Update attendee_details
            UPDATE booking SET attendee_details = '{"name": "Unknown", "email": "unknown@example.com"}'::jsonb 
            WHERE attendee_details IS NULL;
            
            -- Update ticket_code
            UPDATE booking SET ticket_code = substr(md5(random()::text), 1, 8) 
            WHERE ticket_code IS NULL;
            
            -- Update check_in_status
            UPDATE booking SET check_in_status = false 
            WHERE check_in_status IS NULL;
            
            -- Set default for check_in_status first
            ALTER TABLE booking ALTER COLUMN check_in_status SET DEFAULT false;
            
            -- Make columns non-nullable
            ALTER TABLE booking 
                ALTER COLUMN tier_id SET NOT NULL,
                ALTER COLUMN attendee_details SET NOT NULL,
                ALTER COLUMN ticket_code SET NOT NULL,
                ALTER COLUMN check_in_status SET NOT NULL;
            
        EXCEPTION WHEN OTHERS THEN
            -- If any error occurs, rollback the entire transaction
            RAISE NOTICE 'Error occurred: %', SQLERRM;
            RAISE;
        END;
        $$;
        """
    ]
    
    for command in commands:
        op.execute(text(command))

def downgrade():
    # Make columns nullable again using raw SQL
    command = """
    ALTER TABLE booking 
        ALTER COLUMN tier_id DROP NOT NULL,
        ALTER COLUMN attendee_details DROP NOT NULL,
        ALTER COLUMN ticket_code DROP NOT NULL,
        ALTER COLUMN check_in_status DROP NOT NULL,
        ALTER COLUMN check_in_status DROP DEFAULT;
    """
    op.execute(text(command)) 