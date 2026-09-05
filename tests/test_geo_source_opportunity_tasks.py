import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from app.geo.content import routes
from app.geo.content.source_opportunities import build_source_opportunities
from app.geo.content.schemas import SourceOpportunityTaskCreate, TaskUpdate


class OpportunityTaskTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.prompt = SimpleNamespace(id=2, tenant_id=7, question="如何选设备", is_brand_probe=False, last_task_id=None)
        self.row = SimpleNamespace(id=3, prompt_id=2, engine="deepseek", captured_at=datetime(2026, 9, 5),
            simulated=False, sample_mode="openai_compat", note="method=unprimed_json_v2 · analysis=completed",
            mentions_brand=False, cited_urls=["https://source.example/a"], citation_accuracy="unknown")
        self.session = AsyncMock()
        self.session.add = Mock()
        self.session.scalar.side_effect = [self.prompt, None]
        self.session.scalars.return_value = [self.row]
        self.ctx = SimpleNamespace(ensure_tenant=Mock(), user_id=9)
        version = build_source_opportunities([self.row], prompts={2: self.prompt}, own_domains=["brand.example"])["items"][0]["evidence_version"]
        self.req = SourceOpportunityTaskCreate(tenant_id=7, prompt_id=2, snapshot_ids=[3], evidence_version=version)
        for name, value in [("_own_domains_for_tenant", ["brand.example"]),
                            ("_resolve_task_business_id", 4), ("_resolve_active_period_id", 5),
                            ("_sync_task_pipeline", None)]:
            patcher = patch.object(routes, name, new=AsyncMock(return_value=value))
            patcher.start()
            self.addCleanup(patcher.stop)
        async def assign_id():
            self.session.add.call_args.args[0].id = 10
        self.session.flush.side_effect = assign_id

    async def test_creates_draft_with_server_evidence_and_prompt_lock(self):
        result = await routes.create_task_from_source_opportunity(self.req, self.ctx, self.session)
        task = self.session.add.call_args.args[0]
        self.assertTrue(result['created'])
        self.assertEqual(task.brief['source_opportunity']['evidence'][0]['snapshot_id'], 3)
        self.assertEqual(task.brief['source_opportunity']['sample_ids'], [3])
        self.assertEqual(task.target_channels, ['website'])
        self.assertEqual(task.business_id, 4)
        self.assertEqual(self.prompt.last_task_id, 10)
        self.assertIn('FOR UPDATE', str(self.session.scalar.call_args_list[0].args[0]))
        sql = self.session.scalars.call_args.args[0].compile()
        self.assertEqual(sql.params['tenant_id_1'], 7)
        self.assertEqual(sql.params['prompt_id_1'], 2)
        self.session.commit.assert_awaited_once()

    async def test_existing_task_reused_without_overwriting_brief(self):
        self.session.scalar.side_effect = [self.prompt, 88]
        result = await routes.create_task_from_source_opportunity(self.req, self.ctx, self.session)
        self.assertEqual(result, dict(created=False, task_id=88, editor_path='/geo/tasks/88'))
        self.session.add.assert_not_called()
        self.session.scalars.assert_not_awaited()

    async def test_missing_or_other_tenant_snapshot_rejected(self):
        self.session.scalars.return_value = []
        with self.assertRaises(HTTPException) as error:
            await routes.create_task_from_source_opportunity(self.req, self.ctx, self.session)
        self.assertEqual(error.exception.status_code, 409)
        self.session.add.assert_not_called()
        self.session.commit.assert_not_awaited()

    async def test_changed_analysis_rejected(self):
        self.row.note = 'method=unprimed_json_v2 · analysis=needs_review'
        with self.assertRaises(HTTPException) as error:
            await routes.create_task_from_source_opportunity(self.req, self.ctx, self.session)
        self.assertEqual(error.exception.status_code, 409)
        self.session.add.assert_not_called()

    async def test_tenant_authorization_precedes_database_access(self):
        self.ctx.ensure_tenant.side_effect = HTTPException(403)
        with self.assertRaises(HTTPException):
            await routes.create_task_from_source_opportunity(self.req, self.ctx, self.session)
        self.session.scalar.assert_not_awaited()

    async def test_missing_prompt_rejected(self):
        self.session.scalar.side_effect = [None]
        with self.assertRaises(HTTPException) as error:
            await routes.create_task_from_source_opportunity(self.req, self.ctx, self.session)
        self.assertEqual(error.exception.status_code, 404)

    async def test_changed_raw_answer_rejected_even_if_labels_unchanged(self):
        self.row.raw_text = "原文已被修改"
        with self.assertRaises(HTTPException) as error:
            await routes.create_task_from_source_opportunity(self.req, self.ctx, self.session)
        self.assertEqual(error.exception.status_code, 409)
        self.session.add.assert_not_called()

    async def test_changed_citation_rejected_even_if_still_opportunity(self):
        self.row.cited_urls = ["https://new.example/a"]
        with self.assertRaises(HTTPException) as error:
            await routes.create_task_from_source_opportunity(self.req, self.ctx, self.session)
        self.assertEqual(error.exception.status_code, 409)
        self.session.commit.assert_not_awaited()

    async def test_brief_edit_preserves_original_source(self):
        original = {'prompt_id': 2, 'evidence': [{'snapshot_id': 3}]}
        task = SimpleNamespace(id=10, brief={'source_opportunity': original}, status='draft')
        with patch.object(routes, '_get_task', new=AsyncMock(return_value=task)), patch.object(
            routes, '_task_payload', new=AsyncMock(return_value={})
        ):
            await routes.patch_task(10, TaskUpdate(brief={'notes': '编辑后的简报'}), 7, self.ctx, self.session)
        self.assertEqual(task.brief['notes'], '编辑后的简报')
        self.assertEqual(task.brief['source_opportunity'], original)
