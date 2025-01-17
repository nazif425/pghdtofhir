"""empty message

Revision ID: ecc76e29a09c
Revises: 
Create Date: 2024-10-09 15:23:16.772703

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'ecc76e29a09c'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('application_data',
    sa.Column('application_data_id', sa.Integer(), nullable=False),
    sa.Column('fitbit_client_id', sa.String(length=255), nullable=False),
    sa.Column('fitbit_secret', sa.String(length=255), nullable=False),
    sa.Column('fitbit_refresh_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('fhir_server_url', sa.String(length=255), nullable=False),
    sa.PrimaryKeyConstraint('application_data_id')
    )
    op.create_table('call_session',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.String(length=50), nullable=False),
    sa.Column('validated', sa.Boolean(), nullable=True),
    sa.Column('practitioner_id', sa.String(length=50), nullable=True),
    sa.Column('patient_id', sa.String(length=50), nullable=True),
    sa.Column('data', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ehr_system',
    sa.Column('ehr_system_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('base_link', sa.String(length=255), nullable=True),
    sa.Column('api_link', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.PrimaryKeyConstraint('ehr_system_id')
    )
    op.create_table('patient',
    sa.Column('patient_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('phone_number', sa.String(length=15), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.PrimaryKeyConstraint('patient_id')
    )
    op.create_table('practitioner',
    sa.Column('practitioner_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('phone_number', sa.String(length=15), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.PrimaryKeyConstraint('practitioner_id')
    )
    op.create_table('fitbit',
    sa.Column('fitbit_id', sa.Integer(), nullable=False),
    sa.Column('access_token', sa.String(length=255), nullable=False),
    sa.Column('refresh_token', sa.String(length=255), nullable=False),
    sa.Column('refresh_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.Column('patient_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['patient_id'], ['patient.patient_id'], ),
    sa.PrimaryKeyConstraint('fitbit_id')
    )
    op.create_table('identity',
    sa.Column('identity_id', sa.Integer(), nullable=False),
    sa.Column('practitioner_id', sa.Integer(), nullable=True),
    sa.Column('practitionerEHR_id', sa.String(length=255), nullable=True),
    sa.Column('patient_id', sa.Integer(), nullable=True),
    sa.Column('patientEHR_id', sa.String(length=255), nullable=False),
    sa.Column('ehr_system_id', sa.Integer(), nullable=False),
    sa.Column('patient_email', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
    sa.ForeignKeyConstraint(['ehr_system_id'], ['ehr_system.ehr_system_id'], ),
    sa.ForeignKeyConstraint(['patient_id'], ['patient.patient_id'], ),
    sa.ForeignKeyConstraint(['practitioner_id'], ['practitioner.practitioner_id'], ),
    sa.PrimaryKeyConstraint('identity_id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('identity')
    op.drop_table('fitbit')
    op.drop_table('practitioner')
    op.drop_table('patient')
    op.drop_table('ehr_system')
    op.drop_table('call_session')
    op.drop_table('application_data')
    # ### end Alembic commands ###
