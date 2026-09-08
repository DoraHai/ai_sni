"""Synthetic SEM fixtures only; no test-module imports or application startup.

HTTP tests still override JWT context and mock module/identity guards separately.
Native PG tests opt in explicitly; these fixtures never connect a configured DB.
"""
import os
from contextlib import contextmanager
from datetime import date, datetime

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1:1/test")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=")
os.environ.setdefault("ADMIN_API_KEY", "local-test-only")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")

from sqlalchemy import Column, JSON, MetaData, Table, create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import BaiduAccount, Keyword, KeywordHourlyReport, KeywordRegionReport, KwReportSnapshot, SearchTermReport

START, END = date(2026, 9, 1), date(2026, 9, 3)

class ReadSession:
    def __init__(self, session):
        self.session = session

    async def execute(self, stmt):
        return self.session.execute(stmt)

    async def scalar(self, stmt):
        return self.session.scalar(stmt)

    async def scalars(self, stmt):
        return self.session.scalars(stmt)


def make_sqlite_engine():
    return create_engine("sqlite://", poolclass=StaticPool,
                         connect_args={"check_same_thread": False})


def only_select(conn, cursor, statement, parameters, context, executemany):
    assert statement.lstrip().upper().startswith("SELECT"), statement


@contextmanager
def readonly_session(engine):
    """Attach after fixture writes; remove listener before disposing the engine."""
    event.listen(engine, "before_cursor_execute", only_select)
    try:
        with Session(engine) as session:
            yield ReadSession(session)
    finally:
        event.remove(engine, "before_cursor_execute", only_select)
        engine.dispose()


def seed_report_fixture(conn):
    conn.execute(text("CREATE TABLE baidu_accounts (id INTEGER, tenant_id INTEGER, status TEXT)"))
    conn.execute(text("""INSERT INTO baidu_accounts VALUES
      (11,1,'active'),(12,1,'inactive'),(13,1,'archived'),(14,1,'disabled'),
      (21,2,'active'),(31,3,'archived')"""))
    conn.execute(text("CREATE TABLE kw_report_snapshots (tenant_id INTEGER, baidu_account_id INTEGER, report_date DATE, device INTEGER, cost NUMERIC, click INTEGER, impression INTEGER, fetched_at DATETIME)"))
    conn.execute(text("""INSERT INTO kw_report_snapshots VALUES
      (1,11,'2026-09-01',0,10,2,100,'2026-09-02 01:00:00'),
      (1,12,'2026-09-01',1,30,3,100,'2026-09-02 02:00:00'),
      (1,13,'2026-09-01',1,500,50,1000,'2026-09-02 02:30:00'),
      (1,14,'2026-09-01',1,70,7,140,'2026-09-02 02:45:00'),
      (1,NULL,'2026-09-01',9,5,1,0,'2026-09-02 03:00:00'),
      (1,11,'2026-09-03',0,0,0,0,'2026-09-04 01:00:00'),
      (2,21,'2026-09-01',0,999,99,999,'2026-09-02 01:00:00')"""))


def make_fixture_tables(native_json=False):
    metadata = MetaData()
    tables = {}
    # Only synthetic table DDL, never Alembic or application metadata.create_all.
    for model in (BaiduAccount,Keyword,KeywordHourlyReport,KeywordRegionReport,KwReportSnapshot,SearchTermReport):
        tables[model] = Table(model.__tablename__,metadata,*[
            Column(c.name,JSON() if isinstance(c.type,JSONB) and not native_json else c.type,nullable=True) for c in model.__table__.columns])
    return metadata, tables



def seed_fixture(conn, tables):
    stamp = datetime(2026,9,4,1)
    conn.execute(tables[BaiduAccount].insert(),[
        dict(id=11,tenant_id=1,status="active"),
        dict(id=12,tenant_id=1,status="inactive"),
        dict(id=13,tenant_id=1,status="archived"),
        dict(id=14,tenant_id=1,status="disabled"),
        dict(id=21,tenant_id=2,status="active"),
        dict(id=31,tenant_id=3,status="archived"),
    ])
    for id_,aid,tid in [(1,11,1),(2,12,1),(3,None,1),(4,21,2)]:
        conn.execute(tables[Keyword].insert(),dict(id=id_,tenant_id=tid,baidu_account_id=aid,keyword_id=100,
                     keyword="test%词",campaign_id=7,adgroup_id=8,price=1,pause=False,synced_at=stamp))
    conn.execute(tables[Keyword].insert(),dict(id=5,tenant_id=1,baidu_account_id=11,keyword_id=101,keyword="no report"))
    conn.execute(tables[Keyword].insert(),dict(id=6,tenant_id=1,baidu_account_id=13,keyword_id=102,
        keyword="archived history",campaign_id=9,adgroup_id=10,price=3,pause=True,synced_at=stamp))
    for aid,tid,cost,raw in [(11,1,10,{"ocpcConversionsDetail2":"2"}),(12,1,50,{"ocpcConversionsDetail2":0}),
                             (None,1,7,{}),(21,2,999,{"ocpcConversionsDetail2":999})]:
        conn.execute(tables[KwReportSnapshot].insert(),dict(tenant_id=tid,baidu_account_id=aid,keyword_id=100,
            report_date=date(2026,9,1),device=0,cost=cost,click=2,impression=100,fetched_at=stamp,raw_metrics=raw))
    conn.execute(tables[KwReportSnapshot].insert(),dict(tenant_id=1,baidu_account_id=11,keyword_id=100,
        report_date=date(2026,9,3),device=1,cost=0,click=0,impression=0,fetched_at=stamp,raw_metrics={"ocpcConversionsDetail2":False}))
    conn.execute(tables[KwReportSnapshot].insert(),dict(tenant_id=1,baidu_account_id=13,keyword_id=102,
        report_date=date(2026,9,1),device=1,cost=500,click=50,impression=1000,fetched_at=stamp,
        raw_metrics={"ocpcConversionsDetail2":5}))
    for level,name in [("province","省A"),("city","市A")]:
        conn.execute(tables[KeywordRegionReport].insert(),dict(tenant_id=1,baidu_account_id=11,keyword_id=100,
            report_date=date(2026,9,1),region_level=level,region_name=name,cost=10,click=2,impression=100,
            fetched_at=datetime(2026,9,2,1)))
    conn.execute(tables[KeywordRegionReport].insert(),dict(tenant_id=1,baidu_account_id=12,keyword_id=100,
        report_date=date(2026,9,1),region_level="city",region_name="市B",cost=50,click=2,impression=100,fetched_at=stamp))
    conn.execute(tables[KeywordHourlyReport].insert(),dict(tenant_id=1,baidu_account_id=11,keyword_id=100,
        report_date=date(2026,9,1),report_datetime=datetime(2026,9,1,9),hour=9,cost=0,click=0,impression=0,
        fetched_at=datetime(2026,9,2,2)))
    conn.execute(tables[KeywordRegionReport].insert(),dict(tenant_id=1,baidu_account_id=13,keyword_id=102,
        report_date=date(2026,9,1),region_level="province",region_name="归档省",cost=500,click=50,
        impression=1000,fetched_at=stamp))
    conn.execute(tables[KeywordHourlyReport].insert(),dict(tenant_id=1,baidu_account_id=13,keyword_id=102,
        report_date=date(2026,9,1),report_datetime=datetime(2026,9,1,10),hour=10,cost=500,click=50,
        impression=1000,fetched_at=stamp))
    for id_,aid,start,end,click,imp in [(1,11,date(2026,9,1),date(2026,9,3),2,100),
        (2,12,date(2026,8,1),date(2026,8,31),None,100),(3,11,date(2026,9,1),date(2026,9,3),0,0),
        (4,13,date(2026,7,1),date(2026,7,31),50,1000)]:
        conn.execute(tables[SearchTermReport].insert(),dict(id=id_,tenant_id=1,baidu_account_id=aid,
            query_word="搜索%词" if id_ != 3 else "别词",trigger_keyword="test%词",campaign_id=7,adgroup_id=8,
            window_start=start,window_end=end,synced_at=stamp,click=click,impression=imp,cost=10,ctr=999))
