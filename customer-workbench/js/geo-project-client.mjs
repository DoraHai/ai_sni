import {geoClientRoute, geoClientQuery} from './geo-client-routes.mjs';
const fail = (code, status) => {
  throw Object.assign(Error(code), {code, status});
};
export function createGeoProjectClient({transport, getContext}) {
  let generation = 0;
  const key = (c) => JSON.stringify([c.connected, c.tenantId, c.projectId, c.userId, c.revision]);
  return {
    invalidate() {
      generation++;
    },
    async read(resource, params = {}) {
      const context = {...getContext()},
        stamp = generation,
        scope = key(context);
      if (!context.connected) fail('GEO_CONTEXT_CHANGED');
      const path = `/api/v1/geo/projects/${context.projectId}/${resource === 'executions' ? 'executions' : 'client/' + resource}`;
      const url = new URL(path, 'https://scope.invalid');
      url.searchParams.set('tenant_id', String(context.tenantId));
      for (const [name, value] of Object.entries(params))
        if (value !== null && value !== undefined && value !== '')
          url.searchParams.set(name, String(value));
      const route = geoClientRoute(path);
      if (!route || !geoClientQuery(url, route, context)) fail('GEO_ROUTE_DENIED');
      const current = () => {
        if (stamp !== generation || key(getContext()) !== scope) fail('GEO_CONTEXT_CHANGED');
      };
      const response = await transport(url.pathname + url.search, {method: 'GET'});
      current();
      if (!response.ok)
        fail(
          [404, 405].includes(response.status)
            ? 'GEO_NOT_OPEN'
            : response.status === 409
              ? 'GEO_SCOPE_CHANGED'
              : response.status === 400
                ? params.cursor
                  ? 'GEO_CURSOR_INVALID'
                  : params.week_end
                    ? 'GEO_INVALID_WEEK'
                    : 'GEO_READ_FAILED'
                : 'GEO_READ_FAILED',
          response.status,
        );
      const value = await response.json();
      current();
      if (resource === 'executions') {
        if (
          value?.project_id !== context.projectId ||
          !Array.isArray(value.items) ||
          !Array.isArray(value.prompts) ||
          !value.service_plan ||
          typeof value.effective_pause !== 'boolean'
        )
          fail('GEO_RESPONSE_INVALID');
      } else {
        if (
          value?.schema_version !== 'geo.client.v1' ||
          value.tenant_id !== context.tenantId ||
          value.project_id !== context.projectId ||
          value.read_only !== true ||
          !value.data ||
          !value.scope ||
          !value.basis
        )
          fail('GEO_RESPONSE_INVALID');
        if (
          value.scope.ownership_basis !== 'current_project_binding' ||
          !['bound', 'unbound'].includes(value.scope.binding_state) ||
          value.basis.kind !== 'saved_records'
        )
          fail('GEO_RESPONSE_INVALID');
        if (['overview', 'visibility', 'questions', 'answers'].includes(resource.split('/')[0])) {
          const week = value.basis.period?.week_end;
          if (
            !/^\d{4}-\d{2}-\d{2}$/.test(week || '') ||
            value.basis.period?.closed !== true ||
            value.basis.period?.timezone !== 'Asia/Shanghai' ||
            (params.week_end && week !== params.week_end)
          )
            fail('GEO_RESPONSE_INVALID');
        }
        const data = value.data,
          ids = resource.split('/'),
          object = (v) => v && typeof v === 'object' && !Array.isArray(v);
        if (
          resource === 'overview' &&
          (!object(data.content) || !object(data.monitoring) || !object(data.weekly))
        )
          fail('GEO_RESPONSE_INVALID');
        if (
          resource === 'visibility' &&
          (!object(data.current) ||
            !object(data.previous) ||
            !object(data.comparison) ||
            !Array.isArray(data.engines))
        )
          fail('GEO_RESPONSE_INVALID');
        if (
          ids.length === 2 &&
          ids[0] === 'questions' &&
          (!object(data.question) ||
            data.question.id !== Number(ids[1]) ||
            !Array.isArray(data.by_engine))
        )
          fail('GEO_RESPONSE_INVALID');
        if (
          ids.length === 2 &&
          ids[0] === 'answers' &&
          (!object(data.item) ||
            data.item.id !== Number(ids[1]) ||
            typeof data.raw_text !== 'string' ||
            !Array.isArray(data.citations))
        )
          fail('GEO_RESPONSE_INVALID');
        if (
          ids.length === 2 &&
          ids[0] === 'content' &&
          (!object(data.task) ||
            data.task.id !== Number(ids[1]) ||
            (data.master !== null &&
              (!object(data.master) || data.master.task_id !== Number(ids[1]))))
        )
          fail('GEO_RESPONSE_INVALID');
        if (ids.length === 4) {
          const row = ids[2] === 'variants' ? data.variant : data.article;
          if (!object(row) || row.id !== Number(ids[3]) || row.task_id !== Number(ids[1]))
            fail('GEO_RESPONSE_INVALID');
        }
        const list =
          ['questions', 'answers', 'content', 'deliveries'].includes(resource) ||
          /^content\/\d+\/variants$/.test(resource);
        if (list) {
          const p = data.pagination;
          if (
            !p ||
            !Array.isArray(data.items) ||
            p.returned_count !== data.items.length ||
            !Number.isSafeInteger(p.total_count) ||
            p.total_count < data.items.length ||
            typeof p.has_more !== 'boolean' ||
            typeof p.truncated !== 'boolean' ||
            (p.has_more &&
              (typeof p.next_cursor !== 'string' || !p.next_cursor || p.truncated !== true)) ||
            (!p.has_more && (p.next_cursor !== null || p.truncated !== false))
          )
            fail('GEO_RESPONSE_INVALID');
        }
      }
      return value;
    },
  };
}
