export const healthFixture=(module='seo')=>({schema:1,module,scope:{kind:'global',tenant_id:null},
  state:'available',as_of:'2026-10-11T02:00:10Z',counts:{projects:1,runs:4,pending_human:1,unknown_cost:null},
  rows:[{tenant_id:1,scope_id:9,project_state:'paused',run_state:'waiting_human',pending_human:1,unknown_cost:null,
    cycle_enabled:false,updated_at:'2026-10-11T02:00:00Z'}],truncated:false,
  queue:{state:'available',queued:0,running:1,unknown:1},
  worker:{state:'active',verified:true,last_tick_at:'2026-10-11T02:00:00Z',evidence:{kind:'local_tick',scope:'this_process'}}});
