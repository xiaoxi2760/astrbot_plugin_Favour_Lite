# -*- coding: utf-8 -*-
"""QQ 头像拉取 —— 带进程内 TTL 缓存 + 默认头像识别。

和 astrbot_plugin_denia_core 的 core/affection_card.py 用同一数据源
（q1.qlogo.cn），因为两个插件的好感度卡并排展示时，头像来源不一致会很出戏。

关于 q1.qlogo.cn 的实测行为（踩过的坑，都写在下面）：

1. **s 参数是白名单，不是任意值。** 实测 40/100/140/160/640 返回图片；
   50/60/80/120/180/200/300/400/500 一律 HTTP 400 空响应。用非法档位时
   Image.open 会抛 UnidentifiedImageError。
   本模块只用 100（排行小图）和 640（个人面板大图），两个档位都验证过可用。

2. **s=240 是个坏档位。** 对任意 QQ 号（包括真实存在的号）都返回同一张
   40x40 灰色剪影，看起来像成功了其实是默认图。已列入黑名单，别用。

3. **无头像 / 不存在的号会回落到默认剪影，且尺寸远小于请求值。**
   s=640 时回落成 40x40，s=100 时回落成 100x100。所以「拿到 200」不等于
   「拿到真头像」—— 默认图按内容哈希识别（见 _DEFAULT_MD5），识别为默认图
   就返回 None，让渲染层画昵称首字，比糊成一团的灰色剪影好看得多。

4. **延迟抖动很大**：实测单次 47ms ~ 2.4s。超时给到 12s，别卡太紧。

5. **失败缓存必须短**。早期版本用 5 分钟，结果一次超时就把某个用户锁死
   5 分钟，表现成「同一个群里有人有头像有人没有、过一阵又反过来了」。
   现在压到 30s，网络一恢复立刻就能补上。

其他设计要点：
  * 成功缓存 6 小时；缓存上限 200 条，超了丢最旧的一半
  * 批量拉取限流，避免整页 20 个头像同时砸向同一个 CDN
  * aiohttp 延迟导入，缺依赖静默降级
  * 只对纯数字 QQ 号拉取，非 QQ 平台的用户 id 直接跳过
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from io import BytesIO

AVATAR_URL = "https://q1.qlogo.cn/g?b=qq&s={s}&nk={uid}"

# 实测可用档位。其余数值会拿到 HTTP 400 空响应。
SIZE_RANK = 100        # 排行榜行内小图
SIZE_PROFILE = 640     # 个人面板大图
VALID_SIZES = (40, 100, 140, 160, 640)   # 240 虽返回 200 但恒为默认图，故排除

AVATAR_TTL = 6 * 3600       # 拉成功缓存 6 小时
AVATAR_FAIL_TTL = 30       # 拉失败只缓存 30 秒：宁可多请求一次，也不要把抖动放大成几分钟的空白
AVATAR_CACHE_MAX = 200
AVATAR_TIMEOUT = 12.0
FETCH_CONCURRENCY = 5       # 整页排行榜一次可能有 20 个人，别一起砸过去

# QQ 对「没设头像 / 号不存在」回落的默认图，内容哈希（md5）。
# 尺寸和档位绑定，同一档位下所有用户拿到的是同一张图。
# 加进去的哈希都是 QQ 自己的占位图，不可能是真人头像，误判代价为零。
_DEFAULT_MD5 = frozenset({
    "acef72340ac0e914090bd35799f5594e",  # 40x40 灰色剪影（s=640 时对无头像用户的回落）
    "bad9cbb852b22fe58e62f3f23c7d63d2",  # 40x40 透明占位
    "bb7257abd317126fc3fd3e29ea118958",  # 100x100 灰色剪影（s=100 时的回落）
    "4700116072a9eba9330a81fbbe49b7d5",  # 100x100 透明占位
})

_cache: dict[str, tuple[float, object]] = {}
_last_error: dict[str, str] = {}


def _is_qq(uid: str) -> bool:
    u = str(uid or "").strip()
    return bool(u) and u.isdigit() and 5 <= len(u) <= 12


def _prune() -> None:
    if len(_cache) <= AVATAR_CACHE_MAX:
        return
    for k in list(_cache)[: max(1, len(_cache) // 2)]:
        _cache.pop(k, None)


def _looks_default(img, md5: str, requested: int) -> bool:
    """判断拿到的是不是 QQ 的默认占位图。"""
    if md5 in _DEFAULT_MD5:
        return True
    # 兜底：QQ 回落默认图时给的尺寸远小于请求值。
    # 正常真头像在 s=100 / s=640 下至少也是 100px 宽。
    try:
        return max(img.size) < 64
    except Exception:
        return False


async def fetch_avatar(uid: str, size: int = SIZE_PROFILE):
    """拉 QQ 头像。

    返回 PIL Image；拉不到 / 识别为默认图 / 非 QQ 号时返回 None，
    由渲染层回退昵称首字。失败原因记在 last_error(uid) 里便于排查。
    """
    uid = str(uid or "").strip()
    if size not in VALID_SIZES:
        size = SIZE_PROFILE if size >= 200 else SIZE_RANK
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
    reason = ""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    AVATAR_URL.format(s=size, uid=uid),
                    timeout=aiohttp.ClientTimeout(total=AVATAR_TIMEOUT)) as resp:
                if resp.status != 200:
                    reason = f"HTTP {resp.status}"
                else:
                    data = await resp.read()
                    if not data:
                        reason = "空响应体"
                    else:
                        try:
                            cand = Image.open(BytesIO(data))
                            cand.load()          # GIF 只取首帧，卡片上也只用静态帧
                            md5 = hashlib.md5(data).hexdigest()
                            if _looks_default(cand, md5, size):
                                reason = "QQ 默认占位图"
                            else:
                                img = cand
                        except Exception as e:
                            reason = f"解码失败({type(e).__name__})"
    except asyncio.TimeoutError:
        reason = f"超时>{AVATAR_TIMEOUT:.0f}s"
    except Exception as e:
        reason = f"{type(e).__name__}: {str(e)[:60]}"

    if img is None:
        _last_error[uid] = reason or "未知原因"
    else:
        _last_error.pop(uid, None)

    _prune()
    _cache[uid] = (time.time(), img)
    return img


def last_error(uid: str) -> str:
    """取某个 uid 最近一次拉取失败的原因（成功则为空串）。"""
    return _last_error.get(str(uid or "").strip(), "")


async def fetch_many(uids, size: int = SIZE_RANK) -> dict:
    """批量拉头像，返回 {uid: Image|None}。

    限流并发，逐个 catch，单个失败不影响整批。
    """
    uniq, seen = [], set()
    for u in uids:
        u = str(u or "").strip()
        if u and u not in seen:
            seen.add(u)
            uniq.append(u)
    if not uniq:
        return {}

    sem = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def guarded(u):
        async with sem:
            try:
                return await fetch_avatar(u, size)
            except Exception as e:      # 理论上 fetch_avatar 内部已兜，这里再兜一层
                _last_error[u] = f"{type(e).__name__}: {str(e)[:60]}"
                return None

    results = await asyncio.gather(*(guarded(u) for u in uniq))
    return dict(zip(uniq, results))
