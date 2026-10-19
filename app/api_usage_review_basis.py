"""Shared admission cost basis, compatible with the pre-review ledger schema."""
from sqlalchemy import text

REVIEW_COLUMNS = {'review_version', 'verified_amount', 'verified_currency', 'reviewed_at'}


async def review_columns(session):
    return set((await session.execute(text("""SELECT column_name FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name='api_usage_events'
        AND column_name=ANY(:names)"""), {'names': sorted(REVIEW_COLUMNS)})).scalars())


async def accounted_amount(session):
    columns = await review_columns(session)
    if columns and columns != REVIEW_COLUMNS:
        # A partial installation cannot silently ignore a manual review.
        raise RuntimeError('Incomplete usage review schema')
    if not columns:
        return 'estimated_amount'
    # A terminal-only review deliberately leaves money unknown. Never fall back
    # to the old estimate or reservation after a human review of this event.
    return "(CASE WHEN review_version>0 THEN CASE WHEN verified_currency='CNY' THEN verified_amount END ELSE estimated_amount END)"


async def review_projection(session):
    # Validate partial installation before projecting optional fields.
    amount = await accounted_amount(session)
    if amount == 'estimated_amount':
        return '0 AS review_version,NULL::numeric AS verified_amount,NULL::varchar AS verified_currency,NULL::timestamptz AS reviewed_at'
    return 'review_version,verified_amount,verified_currency,reviewed_at'
