"""Pinned MHT directory is descriptive and never grants executable stages."""
from copy import deepcopy
import pytest
from app.distribution_execution_capabilities import directory, frozen_manifest, validate_manifest


def test_frozen_manifest_preserves_content_types_and_unavailable_adapters():
    manifest = frozen_manifest()
    result = validate_manifest(manifest)
    assert result['stages'] == {} and result['automatic_publish'] is False
    assert all(c['mode'] == 'unavailable' for c in manifest['channels'])
    rows = {r['platform_id']: r for r in directory()}
    assert len(rows) == 12
    assert rows['weibo']['content_types'] == ['post']
    assert rows['douyin']['content_types'] == ['video']
    assert rows['xiaohongshu']['content_types'] == ['image-note', 'video']
    assert rows['linkedin']['content_types'] == ['article', 'post']
    assert sum(r['native_intake'] for r in rows.values()) == 2


@pytest.mark.parametrize('change', ['submit', 'verified', 'mode', 'extra', 'missing'])
def test_manifest_rejects_promoted_or_changed_capabilities(change):
    manifest = deepcopy(frozen_manifest())
    if change == 'submit': manifest['automaticSubmit'] = True
    elif change == 'verified': manifest['channels'][0]['publicationVerified'] = True
    elif change == 'mode': manifest['channels'][0]['mode'] = 'automatic'
    elif change == 'extra': manifest['inventedPermission'] = True
    else: manifest['channels'].pop()
    with pytest.raises(ValueError, match='Unsupported MHT manifest'):
        validate_manifest(manifest)
