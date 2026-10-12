# -*- coding: utf-8 -*-
"""QQ 头像拉取 —— 带进程内 TTL 缓存。

和 astrbot_plugin_denia_core 的 core/affection_card.py 同一套实现与同一数据源
（q1.qlogo.cn），因为两个插件的好感度卡并排展示时，头像来源不一致会很出戏。

设计要点：
  * 成功缓存 6 小时，失败只缓存 5 分钟 —— 一次网络抖动不该让占位头像顶替 6 小时
  * 缓存上限 200 条，超了丢最旧的一半，避免长时间运行后无限增长
  * aiohttp 延迟导入，缺依赖时静默返回 None（渲染层回退昵称首字，不影响出图）
  * 只对纯数字 QQ 号拉取，非 QQ 平台的用户 id 直接跳过
"""
from __future__ import annotations

import time
from io import BytesIO

AVATAR_URL = "https://q1.qlogo.cn/g?b=qq&s={s}&nk={uid}"
AVATAR_TTL = 6 * 3600       # 拉成功缓存 6 小时
AVATAR_FAIL_TTL = 300       # 拉失败只缓存 5 分钟
AVATAR_CACHE_MAX = 200
AVATAR_TIMEOUT = 6.0

_cache: dict[str, tuple[float, object]] = {}


def _is_qq(uid: str) -> bool:
    u = str(uid or "").strip()
    return bool(u) and u.isdigit() and 5 <= len(u) <= 12


def _prune() -> None:
    if len(_cache) <= AVATAR_CACHE_MAX:
        return
    # dict 保序，最旧的排前面
    for k in list(_cache)[: max(1, len(_cache) // 2)]:
        _cache.pop(k, None)


async def fetch_avatar(uid: str, size: int = 640):
    """拉 QQ 头像，返回 PIL Image 或 None。拉不到时调用方画昵称首字占位。"""
    uid = str(uid or "").strip()
    if not _is_qq(uid):
        return None
    try:
        from PIL import Image
    except ImportError:
        return None

    hit = _cache.get(uid)
    if hit:
        cached_at, cached = hit
        ttl = AVATAR_TTL if cached is not None else AVATAR_FAIL_TTL
        if time.time() - cached_at < ttl:
            return cached

    img = None
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    AVATAR_URL.format(s=size, uid=uid),
                    timeout=aiohttp.ClientTimeout(total=AVATAR_TIMEOUT)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    if data:
                        img = Image.open(BytesIO(data))
                        img.load()
    except Exception:
        # 拉不到是常态（网络受限 / 非 QQ 平台 / 对方关闭头像），静默回退
        img = None

    _prune()
    _cache[uid] = (time.time(), img)
    return img


async def fetch_many(uids, size: int = 100) -> dict:
    """批量拉头像，返回 {uid: Image|None}。逐个 catch，单个失败不影响整批。"""
    uniq = []
    seen = set()
    for u in uids:
        u = str(u or "").strip()
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    if not uniq:
        return {}
    import asyncio
    results = await asyncio.gather(
        *(fetch_avatar(u, size) for u in uniq), return_exceptions=True)
    out: dict[str, object] = {}
    for u, r in zip(uniq, results):
        out[u] = None if isinstance(r, BaseException) else r
    return out
