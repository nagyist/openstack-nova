# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""add_tls_port_to_console_auth_tokens

Revision ID: 2903cd72dc14
Revises: d60bddf7a903
Create Date: 2024-07-18 22:55:25.736157
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2903cd72dc14'
down_revision = 'd60bddf7a903'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('console_auth_tokens', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tls_port', sa.Integer()))
