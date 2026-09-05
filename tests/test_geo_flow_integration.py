"""In-memory storage doubles; exercise actual GEO route and calculation functions."""
import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from app.geo.content import routes
from app.geo.content.schemas import SourceOpportunityTaskCreate, TaskUpdate


class GeoFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.prompt = SimpleNamespace(id=2, tenant_id=7, question='设备怎么选？', is_brand_probe=False,
            status='active', unit_id=4, tags=[], last_task_id=None)
        self.unit = SimpleNamespace(id=4, tenant_id=7, business_id=5, name='选型')
        self.business = SimpleNamespace(id=5, tenant_id=7, name='设备')
        self.rows = [SimpleNamespace(id=i, tenant_id=7, prompt_id=2,
            captured_at=datetime(2026, 9, 5, 12), engine='deepseek' if i % 2 else 'doubao',
            sample_mode='openai_compat', simulated=False, raw_text='参考第三方选型说明。',
            mentions_brand=False, cited_urls=['https://source.example/guide'],
            brand_position='absent', sentiment='unknown', competitors=[], citation_format='linked',
            citation_accuracy='unknown', note='method=unprimed_json_v2 · analysis=completed',
            created_by=9, created_at=datetime(2026, 9, 5)) for i in range(1, 4)]
        self.tasks = []
        self.session = AsyncMock()
        self.session.add = Mock(side_effect=self.tasks.append)
        self.session.scalars.side_effect = self.scalars
        self.session.scalar.side_effect = self.scalar
        self.session.flush.side_effect = self.flush
        self.ctx = SimpleNamespace(user_id=9, ensure_tenant=Mock(side_effect=self.authorize))
        for owner, name, value in [
            (routes, '_ensure_tenant_exists', SimpleNamespace(id=7, name='测试客户')),
            (routes, '_own_domains_for_tenant', ['brand.example']),
            (routes, '_resolve_task_business_id', 5),
            (routes, '_resolve_active_period_id', None),
            (routes, '_sync_task_pipeline', None),
        ]:
            p = patch.object(owner, name, new=AsyncMock(return_value=value))
            p.start()
            self.addCleanup(p.stop)
        p = patch('app.geo.content.ai_settings.ensure_ai_setting', new=AsyncMock(
            return_value=SimpleNamespace(monitoring_stance='hybrid')))
        p.start()
        self.addCleanup(p.stop)

    def authorize(self, tenant_id):
        if tenant_id != 7:
            raise HTTPException(403, 'wrong tenant')

    async def scalars(self, statement):
        name = statement.column_descriptions[0]['entity'].__name__
        params = statement.compile().params
        if 'tenant_id_1' in params:
            self.assertEqual(params['tenant_id_1'], 7)
        if name == 'GeoAnswerSnapshot':
            return self.rows
        if name == 'GeoPrompt':
            return [self.prompt]
        if name == 'GeoOptimizationUnit':
            return [self.unit]
        if name == 'GeoOptimizationBusiness':
            return [self.business]
        if name == 'GeoContentTask':
            return self.tasks
        self.fail(f'Unexpected storage read: {name}')

    async def scalar(self, statement):
        name = statement.column_descriptions[0]['entity'].__name__
        if name == 'GeoPrompt':
            return self.prompt
        if name == 'GeoContentTask':
            return self.tasks[0].id if self.tasks else None
        self.fail(f'Unexpected scalar: {name}')

    async def flush(self):
        for i, task in enumerate(self.tasks):
            task.id = i + 100
            task.updated_at = datetime(2026, 9, 5, 15, 59, 59)  # Shanghai 23:59:59

    async def pack(self, **kwargs):
        args = dict(tenant_id=7, from_='2026-09-05', to='2026-09-05', format='json',
            real_only=True, top_domains=10, sample_snapshots=12, task_limit=20,
            business_id=None, unit_id=None, period_id=None, ctx=self.ctx, session=self.session)
        args.update(kwargs)
        return await routes.geo_deliverables_pack(**args)

    async def test_opportunity_task_edit_and_deliverable_flow(self):
        from datetime import date
        insights = await routes.citation_insights(tenant_id=7, date_from=date(2026, 9, 5),
            date_to=date(2026, 9, 5), days=14, ctx=self.ctx, session=self.session)
        opportunity = insights['source_opportunities']['items'][0]
        req = SourceOpportunityTaskCreate(tenant_id=7, prompt_id=2,
            snapshot_ids=opportunity['sample_ids'], evidence_version=opportunity['evidence_version'])
        created = await routes.create_task_from_source_opportunity(req, self.ctx, self.session)
        repeated = await routes.create_task_from_source_opportunity(req, self.ctx, self.session)
        self.assertTrue(created['created'])
        self.assertFalse(repeated['created'])
        self.assertEqual(len(self.tasks), 1)
        task = self.tasks[0]
        source = task.brief['source_opportunity']
        # Avoid unrelated article/fact reads while exercising the actual update route.
        with patch.object(routes, '_get_task', new=AsyncMock(return_value=task)), patch.object(
            routes, '_task_payload', new=AsyncMock(return_value={})
        ):
            await routes.patch_task(task.id, TaskUpdate(brief={'notes': '补充选型事实'}), 7, self.ctx, self.session)
        self.assertEqual(task.brief['source_opportunity'], source)
        pack = await self.pack()
        self.assertEqual(pack['summary']['tasks'], 1)
        self.assertEqual(pack['summary']['snapshots'], 3)
        self.assertEqual(pack['daily_series'][0]['snapshots_visibility'], 3)
        self.assertEqual(pack['business_slices'][0]['snapshots_visibility'], 3)
        self.assertIsNone(pack['business_slices'][0]['engine'])
        markdown = await self.pack(format='md')
        self.assertEqual(markdown.status_code, 200)
        self.assertIn('设备怎么选', markdown.body.decode())
        # A later same-question observation changes the report, not the saved source.
        self.rows.append(SimpleNamespace(**{**vars(self.rows[0]), 'id': 4, 'mentions_brand': True}))
        later = await self.pack()
        self.assertEqual(later['summary']['snapshots'], 4)
        self.assertEqual(task.brief['source_opportunity']['sample_count'], 3)

    async def test_task_window_includes_full_shanghai_day_with_open_end(self):
        for i, value in enumerate([
            datetime(2026, 9, 4, 15, 59, 59),  # outside
            datetime(2026, 9, 4, 16),  # day start
            datetime(2026, 9, 5, 23, 59, 59, tzinfo=timezone(timedelta(hours=8))),
            datetime(2026, 9, 5, 16),  # next day: outside
        ]):
            self.tasks.append(SimpleNamespace(id=i, updated_at=value, prompt_id=2,
                title=str(i), status='draft', pipeline_step='opportunity'))
        pack = await self.pack()
        self.assertEqual([task['id'] for task in pack['tasks']], [1, 2])

    async def test_mixed_method_hides_summary_and_daily_rates(self):
        self.rows[0].note = 'legacy'
        pack = await self.pack()
        self.assertIsNone(pack['summary']['visibility_mention_rate'])
        self.assertIsNone(pack['daily_series'][0]['brand_mention_rate'])
        self.assertIsNone(pack['business_slices'][0]['brand_mention_rate'])

    async def test_closed_period_returns_saved_pack_without_recalculation(self):
        frozen = {'period_name': '已关闭期次', 'headline': {'tasks_in_period': 99}, 'frozen_at': '2026-09-01'}
        self.session.get.return_value = SimpleNamespace(tenant_id=7, status='closed', result_meta={'deliverable_pack': frozen})
        result = await self.pack(period_id=20)
        self.assertEqual(result['headline']['tasks_in_period'], 99)
        markdown = await self.pack(period_id=20, format='md')
        self.assertIn('已关闭期次', markdown.body.decode())
        self.session.scalars.assert_not_awaited()

    async def test_wrong_tenant_stops_before_storage(self):
        with self.assertRaises(HTTPException) as error:
            await self.pack(tenant_id=8)
        self.assertEqual(error.exception.status_code, 403)
        self.session.scalars.assert_not_awaited()
