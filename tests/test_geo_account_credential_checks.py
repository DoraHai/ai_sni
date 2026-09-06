import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
import pytest
from fastapi import HTTPException
from app.geo.content.routes import verify_social_account

@pytest.mark.parametrize('url,valid', [('https://example.com/publish',True), ('http://example.com',False)])
def test_webhook_configuration_check_does_not_publish_or_claim_connection(url,valid):
    row=NS(auth_type='webhook',credentials_encrypted='encrypted')
    session=NS(commit=AsyncMock())
    with patch('app.geo.content.routes._get_channel_account',AsyncMock(return_value=row)), \
         patch('app.geo.content.connectors.social.decrypt_credentials_json',return_value={'webhook_url':url}):
        run=verify_social_account(1,7,NS(ensure_tenant=Mock()),session)
        if valid:
            result=asyncio.run(run)
            assert result=={'ok':True,'provider':'webhook','check_scope':'configuration'}
        else:
            with pytest.raises(HTTPException) as exc: asyncio.run(run)
            assert exc.value.status_code==400
    session.commit.assert_not_awaited()

def test_wechat_authorization_result_never_returns_token_material():
    row=NS(auth_type='social_api',credentials_encrypted='encrypted')
    with patch('app.geo.content.routes._get_channel_account',AsyncMock(return_value=row)), \
         patch('app.geo.content.connectors.social.decrypt_credentials_json',return_value={'provider':'wechat_mp','app_id':'real_app'}), \
         patch('app.geo.content.connectors.wechat_mp.ensure_wechat_access_token',AsyncMock(return_value=('private-token-value',{}))):
        result=asyncio.run(verify_social_account(1,7,NS(ensure_tenant=Mock()),NS(commit=AsyncMock())))
    assert result['check_scope']=='authorization'
    assert 'token_prefix' not in result and 'private-token' not in str(result)
