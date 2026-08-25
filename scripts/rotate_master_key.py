"""加密主密钥轮换：把库里所有密文从旧密钥换到新密钥。

适用场景：CRYPTO_MASTER_KEY_B64 暴露后更换。
覆盖范围：baidu_accounts 的 access_token_encrypted / refresh_token_encrypted
（新增加密字段时记得把列名加进 ENCRYPTED_COLUMNS）。

用法（在 ECS 上，服务可以不停——脚本是单事务，失败全回滚）：

  cd /opt/sem-backend
  # 1. 生成新密钥（先别写进 .env）
  NEW_KEY=$(.venv/bin/python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())")
  # 2. 轮换（OLD 从当前 .env 读，NEW 显式传入）
  set -a; source .env; set +a
  NEW_CRYPTO_MASTER_KEY_B64="$NEW_KEY" .venv/bin/python scripts/rotate_master_key.py
  # 3. 脚本输出"轮换完成"后，把 .env 的 CRYPTO_MASTER_KEY_B64 换成 $NEW_KEY，重启：
  #    systemctl restart sem-backend
  # 4. 验证：重启后检查 /health，并通过已鉴权的 SEM 页面读取账户状态；禁止恢复匿名账户接口

安全要点：
  - 新密钥经环境变量传入，不进 shell history（外面那行只有变量名）
  - 全程单事务：任何一行解密/重加密失败 → 整体回滚，库保持旧密钥状态
  - 写回前用新密钥做一次解密自检，对不上原文就中止
"""
import asyncio
import base64
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

_NONCE_LEN = 12
_KEY_LEN = 32

# 表 → 需要轮换的加密列
ENCRYPTED_COLUMNS = {
    "baidu_accounts": ["access_token_encrypted", "refresh_token_encrypted"],
}


def _key_from_b64(b64: str, label: str) -> bytes:
    raw = base64.b64decode(b64)
    if len(raw) != _KEY_LEN:
        raise SystemExit(f"{label} 解码后必须是 {_KEY_LEN} 字节，当前 {len(raw)} 字节")
    return raw


def _decrypt(key: bytes, ciphertext_b64: str) -> str:
    raw = base64.b64decode(ciphertext_b64)
    return AESGCM(key).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], None).decode("utf-8")


def _encrypt(key: bytes, plaintext: str) -> str:
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    old_b64 = os.environ.get("CRYPTO_MASTER_KEY_B64")
    new_b64 = os.environ.get("NEW_CRYPTO_MASTER_KEY_B64")
    if not (database_url and old_b64 and new_b64):
        raise SystemExit(
            "需要环境变量 DATABASE_URL / CRYPTO_MASTER_KEY_B64（旧）/ NEW_CRYPTO_MASTER_KEY_B64（新）"
        )
    if old_b64 == new_b64:
        raise SystemExit("新旧密钥相同，无需轮换")

    old_key = _key_from_b64(old_b64, "旧密钥")
    new_key = _key_from_b64(new_b64, "新密钥")

    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    from app.models import BaiduAccount  # noqa: E402  延迟导入避免 app.config 校验拦路

    rotated = 0
    async with session_factory() as session:
        accounts = (await session.scalars(select(BaiduAccount))).all()
        for acc in accounts:
            for col in ENCRYPTED_COLUMNS["baidu_accounts"]:
                old_ct = getattr(acc, col)
                if not old_ct:
                    continue
                plaintext = _decrypt(old_key, old_ct)  # 旧密钥解不开会抛异常 → 回滚
                new_ct = _encrypt(new_key, plaintext)
                if _decrypt(new_key, new_ct) != plaintext:  # 写回前自检
                    raise SystemExit(f"自检失败：{col} 新密文解不回原文，已中止")
                setattr(acc, col, new_ct)
                rotated += 1
        await session.commit()
    await engine.dispose()

    print(f"轮换完成：{len(accounts)} 个账户，{rotated} 个密文字段已换新密钥。")
    print("下一步：更新 .env 的 CRYPTO_MASTER_KEY_B64 为新值，然后 systemctl restart sem-backend")


if __name__ == "__main__":
    asyncio.run(main())
