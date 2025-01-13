"""empty message

Revision ID: c5f4d38f45a5
Revises: 0c2b3c064586
Create Date: 2024-12-16 11:39:18.586645

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5f4d38f45a5'
down_revision = '0c2b3c064586'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('request', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rdf_file', sa.String(length=255), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('request', schema=None) as batch_op:
        batch_op.drop_column('rdf_file')

    # ### end Alembic commands ###
