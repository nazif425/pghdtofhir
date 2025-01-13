"""empty message

Revision ID: a3869abcbf05
Revises: 48dfd9f500b2
Create Date: 2025-01-06 15:29:15.486411

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3869abcbf05'
down_revision = '48dfd9f500b2'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('identity', schema=None) as batch_op:
        batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_identity_organization_id', 'organization', ['organization_id'], ['organization_id'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('identity', schema=None) as batch_op:
        batch_op.drop_constraint('fk_identity_organization_id', type_='foreignkey')
        batch_op.drop_column('organization_id')

    # ### end Alembic commands ###