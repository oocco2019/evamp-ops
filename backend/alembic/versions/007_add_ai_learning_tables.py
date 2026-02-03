"""Add AI learning tables: style_profiles, procedures, draft_feedback

Revision ID: 007_add_ai_learning_tables
Revises: 006_add_email_templates
Create Date: 2026-02-02

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007_add_ai_learning_tables'
down_revision = '006_add_email_templates'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # StyleProfile table
    op.create_table(
        'style_profiles',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('greeting_patterns', sa.Text(), nullable=True, comment='Common greetings used'),
        sa.Column('closing_patterns', sa.Text(), nullable=True, comment='Common sign-offs used'),
        sa.Column('tone_description', sa.Text(), nullable=True, comment='Overall tone: friendly, professional, etc.'),
        sa.Column('empathy_patterns', sa.Text(), nullable=True, comment='How empathy is expressed'),
        sa.Column('solution_approach', sa.Text(), nullable=True, comment='How solutions are offered'),
        sa.Column('common_phrases', sa.Text(), nullable=True, comment='Frequently used phrases'),
        sa.Column('response_length', sa.String(50), nullable=True, comment='short/medium/long'),
        sa.Column('style_summary', sa.Text(), nullable=True, comment='Complete style guide for AI'),
        sa.Column('messages_analyzed', sa.Integer(), default=0, nullable=False),
        sa.Column('is_approved', sa.Boolean(), default=False, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

    # Procedures table
    op.create_table(
        'procedures',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(100), nullable=False, unique=True, comment='e.g. proof_of_fault'),
        sa.Column('display_name', sa.String(200), nullable=False, comment='e.g. Ask for Proof of Fault'),
        sa.Column('trigger_phrases', sa.Text(), nullable=True, comment='Comma-separated phrases that trigger this procedure'),
        sa.Column('steps', sa.Text(), nullable=False, comment='What to do/say in this situation'),
        sa.Column('example_messages', sa.Text(), nullable=True, comment='JSON array of example message IDs'),
        sa.Column('is_auto_extracted', sa.Boolean(), default=False, nullable=False),
        sa.Column('is_approved', sa.Boolean(), default=False, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # DraftFeedback table
    op.create_table(
        'draft_feedback',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('thread_id', sa.String(100), nullable=False),
        sa.Column('ai_draft', sa.Text(), nullable=False),
        sa.Column('final_message', sa.Text(), nullable=True),
        sa.Column('was_edited', sa.Boolean(), default=False, nullable=False),
        sa.Column('procedure_name', sa.String(100), nullable=True),
        sa.Column('buyer_message_summary', sa.Text(), nullable=True, comment='What the buyer asked'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('draft_feedback')
    op.drop_table('procedures')
    op.drop_table('style_profiles')
