"""好感度卡片渲染 —— 纯 PIL 本地出图。

两张卡，两套视觉：

1. `render_favour_card` —— 好感度排行卡，粉彩玻璃质感（对齐 astrbot_plugin_cake_denia
   的泡泡初绽主题）：渐变底 + 光晕 + 玻璃泡泡 + 白色圆角卡 + 金银铜段位徽章。
   版式参考 astrbot_plugin_denia_core 的榜单卡（标题区 → 范围 pill → 统计三联 →
   段位行 → 页脚）。

2. `render_profile_card` —— 个人好感度面板，暗梅紫档案风（对齐 astrbot_plugin_denia_core
   的「达妮娅观察记录」个人卡）：渐变页眉横幅 + 环形头像 + RANK 徽章 + 数值大字 +
   引文框 + 三联统计 + 两格详情 + 外框圆角裁切。

denia_core 里依赖其自有数据的区块（观察余额 / 自然恢复上限 / 7 次变化柱状图 /
LLM 评价 / 最近变化原因）本插件没有对应数据，一律不画、不留空位。

排行卡 payload：
    title        主标题
    subtitle     副标题
    scope        范围 pill 文案（如「当前会话」）
    stats        {"total": int, "max": int, "min": int}
    users        [{"rank", "name", "uid", "favour", "relationship", "is_unique", "title"}]
    footer       页脚文案

个人面板 payload：
    name          昵称
    uid           用户 ID（备用，昵称为空时顶上）
    rank          当前排名（字符串，无排名时 "-")
    total_users   全库记录数
    score         好感度
    title         称号
    level         当前等级（来自 favour_levels 配置）
    relationship  关系名
    is_unique     是否唯一关系
    last_interaction 最近互动时间字符串
    created_at    首次记录时间字符串
    min_favour / max_favour  好感度上下限（水位条基准）
    footer        页脚文案

本模块不 import astrbot、不碰数据库 —— 纯函数：payload 进，PNG 文件出。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:  # pragma: no cover
    Image = ImageDraw = ImageFilter = ImageFont = None

SCALE = 2


def s(v) -> int:
    """CSS 像素 -> 画布像素（2x 输出，等价 deviceScaleFactor: 2）。"""
    return int(round(v * SCALE))


# ---------------------------------------------------------------- 调色板
# 对齐小蛋糕默认粉彩主题（white-1 泡泡初绽）
BG_TOP = (255, 246, 251)
BG_MID = (255, 238, 244)
BG_BOT = (255, 228, 239)
CARD_FILL = (255, 255, 255, 244)
CARD_BORDER = (243, 214, 228)
SUB_CARD_FILL = (255, 252, 253, 250)
SUB_CARD_BORDER = (247, 226, 236)

TITLE_C = (101, 67, 42)        # 深棕，跟随小蛋糕标题
SUBTITLE_C = (178, 144, 158)
BODY_C = (90, 70, 80)
MUTED_C = (176, 138, 152)
ACCENT = (233, 84, 107)        # 主强调粉
ACCENT_TEXT = (216, 71, 98)
VALUE_C = (255, 92, 138)       # 数值高亮粉
ROW_SEP = (247, 222, 234, 255)
PILL_BG = (255, 240, 246, 255)
PILL_BORDER = (246, 182, 207)
UNIQ_BG = (255, 236, 226, 255)
UNIQ_BORDER = (247, 190, 160)
UNIQ_C = (214, 124, 76)
AVATAR_RING = (255, 168, 200)
AVATAR_FILL = (255, 236, 244, 255)
AVATAR_TXT = (233, 105, 145)

# 段位色：金银铜 + 平名
RANK_COLORS = [
    (232, 182, 97),    # #e8b661 金
    (201, 209, 222),   # #c9d1de 银
    (207, 154, 107),   # #cf9a6b 铜
]
RANK_PLAIN = (201, 194, 200)

# 光晕 / 泡泡用画布比例定位（cx, cy, radius 均为 0~1 的相对值），
# 渲染时再乘画布尺寸，否则卡片高度随行数变化时装饰会错位。
GLOWS = [
    (0.16, 0.05, 0.30, (255, 255, 255), 70),
    (0.90, 0.28, 0.34, (255, 214, 232), 62),
    (0.40, 0.74, 0.32, (255, 226, 238), 55),
]
BUBBLES = [
    (0.05, 0.09, 34, 0.55, (255, 196, 216)),
    (0.86, 0.16, 26, 0.5, (255, 214, 230)),
    (0.10, 0.62, 22, 0.45, (255, 206, 222)),
    (0.82, 0.86, 30, 0.5, (255, 200, 220)),
    (0.46, 0.03, 18, 0.4, (255, 220, 234)),
]


# ---------------------------------------------------------------- 字体
_FONT_DIRS = [
    "C:/Windows/Fonts",
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/usr/share/fonts/opentype/noto",
    "/usr/share/fonts/opentype/noto-cjk",
    "/usr/share/fonts/truetype/noto-cjk",
    "/usr/share/fonts/noto-cjk",
    "/usr/share/fonts/truetype/wqy",
    "/usr/share/fonts/truetype/droid",
    "/usr/share/fonts/truetype/arphic",
    "/usr/share/fonts/opentype/source-han-sans",
    "/usr/local/share/fonts",
]
_REGULAR = {
    "win32": ("msyh.ttc", "simhei.ttf", "simsun.ttc"),
    "darwin": ("PingFang.ttc", "Hiragino Sans GB.ttc", "STHeiti Medium.ttc"),
    "linux": ("NotoSansCJK-Regular.ttc", "SourceHanSansSC-Regular.otf",
              "wqy-zenhei.ttc", "wqy-microhei.ttc",
              "DroidSansFallbackFull.ttf"),
}
_BOLD = {
    "win32": ("msyhbd.ttc", "simhei.ttf"),
    "darwin": ("PingFang.ttc", "Hiragino Sans GB.ttc"),
    "linux": ("NotoSansCJK-Bold.ttc", "SourceHanSansSC-Bold.otf",
              "wqy-zenhei.ttc", "DroidSansFallbackFull.ttf"),
}
_EMOJI = {
    "win32": ("seguiemj.ttf",),
    "darwin": ("Apple Color Emoji.ttc",),
    "linux": ("NotoColorEmoji.ttf",),
}


def _find(candidates):
    for d in _FONT_DIRS:
        for name in candidates:
            p = Path(d) / name
            if p.exists():
                return str(p)
    return None


class Fonts:
    """按 (CSS 字号, bold) 出字体实例，discover 一次之后走缓存。"""

    def __init__(self, custom_path: str | None = None) -> None:
        key = sys.platform if sys.platform in _REGULAR else "linux"
        reg = custom_path if custom_path and os.path.isfile(custom_path) else _find(_REGULAR[key])
        bold = _find(_BOLD[key]) or reg
        self.reg_path = reg
        self.bold_path = bold
        self.emoji_path = _find(_EMOJI.get(key, ()))
        self._cache: dict[tuple, object] = {}

    def get(self, size_css, bold=False):
        size = max(int(size_css * SCALE), 10)
        k = (size, bold)
        if k not in self._cache:
            path = (self.bold_path if bold else self.reg_path) or self.reg_path
            if path:
                self._cache[k] = ImageFont.truetype(path, size)
            else:
                self._cache[k] = ImageFont.load_default()
        return self._cache[k]

    def emoji(self, size_css):
        size = max(int(size_css * SCALE), 10)
        k = ("emoji", size)
        if k not in self._cache:
            if self.emoji_path:
                try:
                    self._cache[k] = ImageFont.truetype(self.emoji_path, size)
                except Exception:
                    self._cache[k] = None
            else:
                self._cache[k] = None
        return self._cache[k]


# ---------------------------------------------------------------- 绘图基元
def vgrad(w, h, stops):
    """竖直分段渐变。stops = [(pos, (r,g,b)), ...]"""
    img = Image.new('RGB', (1, h))
    px = img.load()
    for y in range(h):
        k = y / (h - 1) if h > 1 else 0
        c = stops[-1][1]
        for i in range(len(stops) - 1):
            p0, c0 = stops[i]
            p1, c1 = stops[i + 1]
            if p0 <= k <= p1:
                t = (k - p0) / (p1 - p0) if p1 > p0 else 0
                c = tuple(int(c0[j] + (c1[j] - c0[j]) * t) for j in range(3))
                break
        px[0, y] = c
    return img.resize((w, h))


def hgrad(w, h, c0, c1):
    img = Image.new('RGB', (w, 1))
    px = img.load()
    for x in range(w):
        t = x / (w - 1) if w > 1 else 0
        px[x, 0] = tuple(int(c0[j] + (c1[j] - c0[j]) * t) for j in range(3))
    return img.resize((w, h))


def glow_layer(w, h, glows):
    """柔和径向光晕层：小图画实心圆 + 高斯模糊再放大。

    glows 元素为 (fx, fy, fr, color, strength)，位置/半径是画布比例。
    """
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    sw, sh = max(w // 4, 1), max(h // 4, 1)
    for fx, fy, fr, color, strength in glows:
        small = Image.new('RGBA', (sw, sh), (0, 0, 0, 0))
        radius = int(fr * w)
        r = max(radius // 4, 2)
        px, py = int(fx * w) // 4, int(fy * h) // 4
        ImageDraw.Draw(small).ellipse(
            [px - r, py - r, px + r, py + r],
            fill=(color[0], color[1], color[2], max(int(strength), 1)))
        small = small.filter(ImageFilter.GaussianBlur(r * 0.6))
        layer = Image.alpha_composite(layer, small.resize((w, h), Image.BILINEAR))
    return layer


def _glass_ball(size, fill):
    """单颗玻璃泡泡：径向渐变球体 + 亮环 + 左上高光。"""
    SS = 4
    S = size * SS
    R = max(size, 24)
    half = R / 2
    grad = Image.new('RGBA', (R, R), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for i in range(int(half), 0, -1):
        t = (1 - i / half) * 0.22
        c = (int(fill[0] + (255 - fill[0]) * t),
             int(fill[1] + (255 - fill[1]) * t),
             int(fill[2] + (255 - fill[2]) * t))
        gd.ellipse([half - i, half - i, half + i, half + i], fill=c + (255,))
    grad = grad.resize((S, S), Image.BICUBIC)

    ball = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    ball.paste(grad, (0, 0), grad)
    d = ImageDraw.Draw(ball)
    lw = max(S // 32, SS)
    rim = tuple(min(255, int(c + (255 - c) * 0.45)) for c in fill[:3])
    d.ellipse([lw // 2, lw // 2, S - lw // 2 - 1, S - lw // 2 - 1],
              outline=rim + (235,), width=lw)
    d.ellipse([S * 0.24, S * 0.18, S * 0.52, S * 0.37], fill=(255, 255, 255, 225))
    return ball.resize((size, size), Image.LANCZOS)


def bubble_layer(w, h, bubbles):
    """玻璃泡泡层。bubbles 元素为 (fx, fy, size, opacity, fill)。"""
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    for (fx, fy, size, opacity, fill) in bubbles:
        size = max(int(size * SCALE), 8)
        ball = _glass_ball(size, fill)
        if opacity < 1.0:
            r_, g_, b_, a = ball.split()
            a = a.point(lambda i: int(i * opacity))
            ball = Image.merge('RGBA', (r_, g_, b_, a))
        layer.alpha_composite(ball, dest=(int(fx * w), int(fy * h)))
    return layer


def rounded_card_layer(w, h, box, radius=26, fill=(255, 255, 255, 240),
                       border=(243, 214, 228), border_w=2, shadow=True,
                       shadow_color=(190, 120, 160, 140), shadow_blur=14,
                       shadow_offset=8):
    """圆角卡片（含投影）作为 RGBA 层返回，供 alpha_composite。"""
    if shadow:
        sh = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle(
            [box[0], box[1] + shadow_offset, box[2], box[3] + shadow_offset],
            radius=radius, fill=shadow_color)
        sh = sh.filter(ImageFilter.GaussianBlur(shadow_blur))
    else:
        sh = Image.new('RGBA', (w, h), (0, 0, 0, 0))

    card = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle(box, radius=radius, fill=fill)
    if border_w > 0:
        cd.rounded_rectangle(box, radius=radius, outline=border, width=border_w)
    return Image.alpha_composite(sh, card)


def pill(w, h, c0, c1, radius):
    """胶囊：水平渐变 + 圆角遮罩。"""
    grad = hgrad(w, h, c0, c1).convert('RGBA')
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def top_wash(w, h, box, radius, color, height, max_alpha=70):
    """卡片顶部同色系渐变洗层（向下淡出），按圆角矩形裁剪。"""
    height = min(int(height), box[3] - box[1])
    grad = Image.new('RGBA', (1, height), (0, 0, 0, 0))
    for y in range(height):
        k = 1 - y / height if height > 1 else 0
        grad.putpixel((0, y), (color[0], color[1], color[2], int(max_alpha * k)))
    grad = grad.resize((box[2] - box[0], height))
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    layer.paste(grad, (box[0], box[1]))
    full = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    full.paste(layer, (0, 0), mask)
    return full


def scene(w, h, card_box, card_radius=26, card_fill=CARD_FILL,
          card_border=CARD_BORDER, **card_kwargs):
    """统一背景：渐变 + 光晕 + 泡泡 + 白色玻璃卡。"""
    img = vgrad(w, h, [(0.00, BG_TOP), (0.42, BG_MID), (1.00, BG_BOT)]).convert('RGBA')
    img = Image.alpha_composite(img, glow_layer(w, h, GLOWS))
    img = Image.alpha_composite(img, bubble_layer(w, h, BUBBLES))
    return Image.alpha_composite(img, rounded_card_layer(
        w, h, card_box, radius=card_radius, fill=card_fill,
        border=card_border, **card_kwargs))


# ---------------------------------------------------------------- 组合件
def _rank_color(idx):
    if idx < len(RANK_COLORS):
        return RANK_COLORS[idx]
    return RANK_PLAIN


def _draw_rank_badge(d, cx, cy, r, idx, fonts):
    """段位徽章：金银铜 + 平名，圆底白字。"""
    c = _rank_color(idx)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c + (255,))
    f = fonts.get(9.5, bold=True)
    txt = str(idx + 1)
    tw = d.textlength(txt, font=f)
    d.text((cx - tw / 2, cy - f.size * 0.55), txt, font=f, fill=(255, 255, 255, 255))


def _draw_avatar(d, cx, cy, r, name, fonts):
    """名号圆：首字代替头像（小蛋糕无头像时的同款观感）。"""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=AVATAR_FILL,
              outline=AVATAR_RING, width=max(s(1.5), 2))
    ch = (name or "?")[0]
    f = fonts.get(10.5, bold=True)
    tw = d.textlength(ch, font=f)
    d.text((cx - tw / 2, cy - f.size * 0.55), ch, font=f, fill=AVATAR_TXT + (255,))


def _draw_tag(img, d, x, y, text, fonts, bg=PILL_BG, border=PILL_BORDER,
              color=ACCENT_TEXT, size=8.5):
    """描边小标签（关系 / 唯一 / 称号）。返回占用宽度。"""
    f = fonts.get(size, bold=False)
    tw = d.textlength(text, font=f)
    w = int(tw + s(11))
    h = s(15)
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2,
                        fill=bg, outline=border, width=max(s(1), 1))
    d.text((x + s(5.5), y + (h - f.size) / 2 - s(1)), text, font=f, fill=color + (255,))
    return w


def _ellipsis(d, text, font, max_w):
    """超长文本按像素裁剪加省略号。"""
    if d.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    ew = d.textlength(ell, font=font)
    out = ""
    for ch in text:
        if d.textlength(out + ch, font=font) > max_w - ew:
            break
        out += ch
    return (out or text[:1]) + ell


# ---------------------------------------------------------------- 主渲染
_W = 700            # CSS 画布宽
_PAD = 26           # 主卡左右内边距


def render_favour_card(payload: dict, out_path, fonts: Fonts) -> Path:
    """好感度榜单卡。payload 见模块 docstring。"""
    users = list(payload.get("users") or [])
    stats = payload.get("stats") or {}

    # ---- 高度按行数自适应
    # 用游标累加而不是"每段给一个固定高"，否则会出现标题区下面一大块空白。
    row_h = 46                       # 每行
    list_pad = 12
    inner_w = _W - _PAD * 2

    title_h = 48 if payload.get("subtitle") else 34     # 标题 + 副标题
    scope_h = 32 if payload.get("scope") else 4         # 范围 pill
    stats_h = 58 + 14                                  # 统计三联 + 下间距
    list_h = list_pad * 2 + max(len(users), 1) * row_h
    foot_h = 26 if payload.get("footer") else 10       # 页脚

    H = _PAD + title_h + scope_h + stats_h + list_h + foot_h + _PAD

    W, HH = s(_W), s(H)
    margin = s(18)                    # 露出背景渐变/泡泡的留白，别让白卡铺满画布
    card_box = [margin, margin, W - margin, HH - margin]
    img = scene(W, HH, card_box)
    img = Image.alpha_composite(
        img, top_wash(W, HH, card_box, s(26), (255, 205, 226), s(title_h + scope_h) + s(20)))
    d = ImageDraw.Draw(img)

    x0 = s(_PAD)
    cx = W // 2

    # ---- 标题区
    f_title = fonts.get(21, bold=True)
    title = payload.get("title") or "好感度榜单"
    tw = d.textlength(title, font=f_title)
    ty = s(_PAD + 6)
    tx = cx - tw / 2
    d.text((tx, ty), title, font=f_title, fill=TITLE_C + (255,))

    f_sub = fonts.get(10.5)
    sub = payload.get("subtitle") or ""
    if sub:
        d.text((cx - d.textlength(sub, font=f_sub) / 2, ty + s(30)), sub,
               font=f_sub, fill=SUBTITLE_C + (255,))

    # 范围 pill
    scope = payload.get("scope") or ""
    if scope:
        f_sc = fonts.get(10, bold=True)
        pw = int(d.textlength(scope, font=f_sc) + s(30))
        ph = s(24)
        px = cx - pw / 2
        py = ty + s(title_h if payload.get("subtitle") else 24)
        img.alpha_composite(
            pill(pw, ph, (255, 205, 226), (255, 228, 240), ph // 2), dest=(int(px), int(py)))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([px, py, px + pw, py + ph], radius=ph // 2,
                            outline=PILL_BORDER, width=max(s(1), 1))
        d.text((cx - d.textlength(scope, font=f_sc) / 2, py + (ph - f_sc.size) / 2 - s(1)),
               scope, font=f_sc, fill=ACCENT_TEXT + (255,))

    # ---- 统计三联
    sy = py + s(scope_h if payload.get("scope") else 0)
    sh = s(58)
    gap = s(10)
    cw = (s(inner_w) - gap * 2) // 3
    cells = [
        ("记录数", str(stats.get("total", len(users)))),
        ("最高好感", str(stats.get("max", 0))),
        ("最低好感", str(stats.get("min", 0))),
    ]
    f_cell_v = fonts.get(17, bold=True)
    f_cell_k = fonts.get(8.5)
    for i, (k, v) in enumerate(cells):
        bx = x0 + i * (cw + gap)
        d.rounded_rectangle([bx, sy, bx + cw, sy + sh], radius=s(12),
                            fill=SUB_CARD_FILL, outline=SUB_CARD_BORDER, width=max(s(1), 1))
        d.text((bx + cw / 2 - d.textlength(v, font=f_cell_v) / 2, sy + s(10)),
               v, font=f_cell_v, fill=ACCENT + (255,))
        d.text((bx + cw / 2 - d.textlength(k, font=f_cell_k) / 2, sy + s(38)),
               k, font=f_cell_k, fill=MUTED_C + (255,))

    # ---- 榜单子卡
    ly = sy + sh + s(14)
    lh = s(list_h)
    d.rounded_rectangle([x0, ly, x0 + s(inner_w), ly + lh], radius=s(16),
                        fill=SUB_CARD_FILL, outline=SUB_CARD_BORDER, width=max(s(1), 1))

    f_name = fonts.get(11, bold=True)
    f_uid = fonts.get(7.5)
    f_val = fonts.get(14, bold=True)
    f_rel = fonts.get(8.5)

    if not users:
        f_empty = fonts.get(10)
        msg = "暂无好感度记录"
        d.text((x0 + s(inner_w) / 2 - d.textlength(msg, font=f_empty) / 2,
                ly + lh / 2 - f_empty.size / 2), msg, font=f_empty, fill=MUTED_C + (255,))

    for i, u in enumerate(users):
        ry = ly + s(list_pad) + i * s(row_h)
        if i:
            d.line([x0 + s(14), ry, x0 + s(inner_w) - s(14), ry],
                   fill=ROW_SEP, width=max(s(1), 1))

        cy = ry + s(row_h) / 2
        # 段位徽章
        _draw_rank_badge(d, x0 + s(17), int(cy), s(11), i, fonts)
        # 名号圆
        raw_name = str(u.get("name") or "").strip()
        _draw_avatar(d, x0 + s(52), int(cy), s(14), raw_name or "未命名", fonts)

        tx = x0 + s(76)
        # 空昵称不拿 uid 顶替，否则 uid 会在主副两行重复出现
        name = _ellipsis(d, raw_name or "未命名用户", f_name, s(120))
        d.text((tx, ry + s(8)), name, font=f_name, fill=BODY_C + (255,))
        sub = str(u.get("uid") or "")
        if sub:
            d.text((tx, ry + s(26)), sub, font=f_uid, fill=MUTED_C + (255,))

        # 关系 / 唯一 / 称号 标签
        tags_x = tx + s(128)
        tags_y = ry + s(11)
        rel = str(u.get("relationship") or "")
        if rel and rel != "无":
            tags_x += _draw_tag(img, d, tags_x, tags_y,
                                _ellipsis(d, rel, f_rel, s(110)), fonts) + s(5)
        if u.get("is_unique"):
            tags_x += _draw_tag(img, d, tags_x, tags_y, "唯一", fonts,
                                bg=UNIQ_BG, border=UNIQ_BORDER, color=UNIQ_C) + s(5)
        ttl = str(u.get("title") or "")
        if ttl and ttl != "-":
            _draw_tag(img, d, tags_x, tags_y, _ellipsis(d, ttl, f_rel, s(90)), fonts,
                      color=(146, 122, 150))

        # 数值右对齐
        val = str(u.get("favour", 0))
        vw = d.textlength(val, font=f_val)
        d.text((x0 + s(inner_w) - s(14) - vw, ry + s(13)), val,
               font=f_val, fill=VALUE_C + (255,))

    # ---- 页脚
    fy = ly + lh + s(6)
    footer = payload.get("footer") or ""
    if footer:
        f_ft = fonts.get(9)
        d.text((cx - d.textlength(footer, font=f_ft) / 2, fy), footer,
               font=f_ft, fill=SUBTITLE_C + (255,))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert('RGB').save(out_path, 'PNG')
    return out_path


# ================================================================ 档案风个人面板
# 视觉对齐 astrbot_plugin_denia_core 的「达妮娅观察记录」个人卡：暗梅紫三段渐变底 +
# 细网格 + 双色径向光晕 + 左侧 tier bar + 渐变页眉横幅 + 外框圆角裁切。
#
# denia_core 里依赖其自有数据的区块（观察余额 / 自然恢复上限 / 近 7 次变化柱状图 /
# LLM 评价 / 最近变化原因）在 Favour Lite 没有对应数据，一律不画、区块直接删掉，
# 用等价的真实字段顶上：水位条=当前好感度在 [下限, 上限] 区间中的位置，
# 最近互动=last_interaction，首次记录=created_at。

A_ACCENT = (212, 139, 184)     # #d48bb8
A_ACCENT_2 = (242, 199, 222)   # #f2c7de
A_GOLD = (241, 212, 138)       # #f1d48a
A_TEXT_1 = (247, 238, 246)     # #f7eef6
A_BG_TOP = (21, 12, 29)
A_BG_MID = (34, 19, 43)
A_BG_BOT = (15, 8, 20)
A_HDR_TOP = (81, 49, 88)       # rgba(88,54,96,.72) 叠在卡片顶部
A_HDR_BOT = (39, 23, 50)       # rgba(41,22,54,.72)
A_GRID_LINE = (242, 199, 222, 9)
A_TIER = (A_ACCENT, A_GOLD, A_ACCENT)

# 各区块高度（CSS 像素，与 denia_core 的 profile.html 盒模型对齐）
_A_MAIN = 28 + 192 + 18
_A_STAT = 12 + 25 + 5 + 10 + 12
_A_STATUS = 12 + 10 + 7 + 15 + 9 + 4 + 5 + 11 + 12


def _arounded(canvas, box, radius, fill=None, outline=None, width=1):
    """圆角矩形画在透明层再合成，避免直接 Draw 打穿已画的像素。"""
    layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=radius, fill=fill,
                                            outline=outline, width=width)
    canvas.alpha_composite(layer)


def _asw(d, text, font, spacing):
    """带字距的文本宽度。"""
    if not text:
        return 0.0
    step = s(spacing)
    return sum(d.textlength(ch, font=font) for ch in text) + step * (len(text) - 1)


def _aspaced(d, xy, text, font, fill, spacing):
    """带字距画一行（原 CSS letter-spacing）。"""
    x, y = xy
    step = s(spacing)
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + step


def _awrap(d, text, font, max_w):
    """CJK 逐字、ASCII 按词的贪婪折行。"""
    lines = []
    for raw in str(text or '').split('\n'):
        if not raw:
            lines.append('')
            continue
        tokens, run = [], ''
        for ch in raw:
            if ch == ' ':
                if run:
                    tokens.append(run)
                    run = ''
                tokens.append(' ')
            elif ord(ch) < 0x2E80:
                run += ch
            else:
                if run:
                    tokens.append(run)
                    run = ''
                tokens.append(ch)
        if run:
            tokens.append(run)
        line = ''
        for tk in tokens:
            cand = line + tk
            if line and d.textlength(cand.lstrip(), font=font) > max_w:
                lines.append(line.rstrip())
                line = '' if tk == ' ' else tk
            else:
                line = cand
        lines.append(line.rstrip())
    return lines or ['']


def _atop_bar(w, h, radius, c0, c1):
    """上圆角、下直角的竖渐变柱。"""
    w, h = max(w, 1), max(h, 1)
    img = vgrad(w, h, [(0.0, c0), (1.0, c1)]).convert('RGBA')
    mask = Image.new('L', (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    md.rectangle((0, h - radius, w - 1, h - 1), fill=255)
    img.putalpha(mask)
    return img


def _acard_base(w, h):
    """档案卡底：三段渐变 + 网格 + 两团径向光晕 + 左侧 tier bar。"""
    canvas = vgrad(w, h, [(0.0, A_BG_TOP), (0.55, A_BG_MID), (1.0, A_BG_BOT)]).convert('RGBA')

    grid = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    step = s(24)
    for x in range(0, w, step):
        gd.line([(x, 0), (x, h)], fill=A_GRID_LINE, width=1)
    for y in range(0, h, step):
        gd.line([(0, y), (w, y)], fill=A_GRID_LINE, width=1)
    canvas.alpha_composite(grid)

    glow = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    gr = s(190)
    ImageDraw.Draw(glow).ellipse(
        (int(w * 0.72) - gr, int(h * 0.18) - gr, int(w * 0.72) + gr, int(h * 0.18) + gr),
        fill=(*A_ACCENT, 42))
    gr2 = s(170)
    ImageDraw.Draw(glow).ellipse(
        (int(w * 0.12) - gr2, int(h * 0.72) - gr2, int(w * 0.12) + gr2, int(h * 0.72) + gr2),
        fill=(*A_GOLD, 22))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(s(60))))

    bar_w = s(5)
    halo = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    halo.paste(Image.new('RGBA', (bar_w, h), (*A_ACCENT, 64)), (0, 0))
    canvas.alpha_composite(halo.filter(ImageFilter.GaussianBlur(s(6))))
    bar = vgrad(bar_w, h, [(0.0, A_TIER[0]), (0.5, A_TIER[1]), (1.0, A_TIER[2])]).convert('RGBA')
    canvas.paste(bar, (0, 0))
    return canvas


def _aheader(card, fonts, title, subtitle, title_size=17):
    """页眉横幅：渐变底 + 底边线 + 左右三道装饰 + 居中标题。"""
    W = card.width
    hdr_h = s(82)
    card.alpha_composite(
        vgrad(W, hdr_h, [(0.0, A_HDR_TOP), (1.0, A_HDR_BOT)]).convert('RGBA'), (0, 0))
    d = ImageDraw.Draw(card)
    d.line([(0, hdr_h - 1), (W, hdr_h - 1)], fill=(*A_ACCENT, 89), width=1)
    for side in (1, -1):
        dy = hdr_h // 2 - s(12)
        for wd in (s(24), s(15), s(8)):
            x0 = s(24) if side == 1 else W - s(24) - wd
            d.rounded_rectangle((x0, dy, x0 + wd, dy + s(2)), radius=s(2),
                                fill=(*A_ACCENT, 184))
            dy += s(7)
    f_title = fonts.get(title_size, bold=True)
    f_sub = fonts.get(10)
    tw = _asw(d, title, f_title, 4)
    _aspaced(d, ((W - tw) / 2, s(24)), title, f_title, (255, 255, 255, 255), 4)
    tw = _asw(d, subtitle, f_sub, 4)
    _aspaced(d, ((W - tw) / 2, s(60)), subtitle, f_sub, (*A_ACCENT_2, 184), 4)


def _afooter(card, fonts, text):
    """页脚条 + 居中字距文案。"""
    W, H = card.width, card.height
    f_y = H - s(34)
    card.alpha_composite(Image.new('RGBA', (W, s(34)), (*A_TEXT_1, 15)), (0, f_y))
    d = ImageDraw.Draw(card)
    d.line([(0, f_y), (W, f_y)], fill=(*A_ACCENT, 51), width=1)
    f_foot = fonts.get(10)
    tw = _asw(d, text, f_foot, 2)
    _aspaced(d, ((W - tw) / 2, f_y + s(12)), text, f_foot, (*A_ACCENT_2, 102), 2)


def _aseal(card):
    """外框描边 + 圆角透明裁切。"""
    W, H = card.width, card.height
    _arounded(card, (0, 0, W - 1, H - 1), s(22), outline=(*A_ACCENT, 56), width=s(1))
    mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), radius=s(22), fill=255)
    card.putalpha(mask)


def _aavatar(card, cx, cy, size, fallback_char, font):
    """贴圆形头像占位：深底 + 首字。"""
    av = Image.new('RGBA', (size, size), (26, 19, 48, 255))
    ad = ImageDraw.Draw(av)
    ch = (fallback_char or '?').strip()[:1] or '?'
    bb = ad.textbbox((0, 0), ch, font=font)
    ad.text((size / 2 - (bb[2] - bb[0]) / 2 - bb[0],
             size / 2 - (bb[3] - bb[1]) / 2 - bb[1]),
            ch, font=font, fill=(*A_ACCENT_2, 255))
    mask = Image.new('L', (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    av.putalpha(mask)
    card.paste(av, (int(cx - size // 2), int(cy - size // 2)), av)


def render_profile_card(payload: dict, out_path, fonts: Fonts) -> Path:
    """个人好感度面板。payload 字段见模块 docstring。"""
    W = s(540)
    PAD = s(26)   # 卡片左右内容边距
    GUT = s(46)   # 引文框左右 padding

    rank = str(payload.get('rank') or '-')
    total_users = int(payload.get('total_users') or 0)
    score = int(payload.get('score') or 0)
    name = str(payload.get('name') or '').strip() or '未知旅人'
    title = str(payload.get('title') or '').strip()
    if title in ('', '-'):
        title = '暂无称号'
    level = str(payload.get('level') or '').strip() or '未分级'
    rel = str(payload.get('relationship') or '').strip() or '无'
    uniq = bool(payload.get('is_unique'))
    last_t = str(payload.get('last_interaction') or '').strip() or '--'
    created = str(payload.get('created_at') or '').strip() or '--'
    min_f = int(payload.get('min_favour') if payload.get('min_favour') is not None else -100)
    max_f = int(payload.get('max_favour') if payload.get('max_favour') is not None else 100)
    footer = str(payload.get('footer') or '').strip() or '好感度插件 · Favour Lite Archive'

    # ---- 先量高度
    probe = ImageDraw.Draw(Image.new('RGBA', (8, 8)))
    summary = f"称号 {title}　·　等级 {level}　·　排名 {rank} / {total_users}"
    f_sum = fonts.get(15)
    sum_lines = _awrap(probe, summary, f_sum, W - PAD * 2 - GUT)
    comment_h = s(17 + 10 + 8) + len(sum_lines) * s(26) + s(17)

    H = s(82 + _A_MAIN) + comment_h + s(18) \
        + s(1 + 33) + s(_A_STAT + 16) + s(_A_STATUS + 16) + s(34)

    card = _acard_base(W, H)
    _aheader(card, fonts, '好感度档案', 'FAVOUR ARCHIVE', 17)
    d = ImageDraw.Draw(card)

    # ---- main：环形头像 + 信息栏
    main_y = s(82) + s(28)
    av_cx, av_cy = s(26 + 59), main_y + s(59)
    d.ellipse((av_cx - s(59), av_cy - s(59), av_cx + s(59), av_cy + s(59)),
              outline=(*A_GOLD, 158), width=s(2))
    d.ellipse((av_cx - s(52), av_cy - s(52), av_cx + s(52), av_cy + s(52)),
              outline=(*A_ACCENT, 140), width=1)
    _aavatar(card, av_cx, av_cy, s(104), name[:1], fonts.get(56, bold=True))
    d = ImageDraw.Draw(card)

    ix = s(26 + 118 + 24)
    iw = W - ix - PAD
    y = main_y
    f_user = fonts.get(27, bold=True)
    d.text((ix, y), _ellipsis(d, name, f_user, iw), font=f_user, fill=(255, 255, 255, 255))
    y += s(40)

    f_badge = fonts.get(11)
    badge = 'RANK #' + rank
    bw = d.textlength(badge, font=f_badge) + s(20)
    _arounded(card, (ix, y, ix + bw, y + s(23)), s(6),
              fill=(0, 0, 0, 87), outline=(*A_ACCENT, 66), width=1)
    d = ImageDraw.Draw(card)
    d.text((ix + s(10), y + s(6)), badge, font=f_badge, fill=(*A_TEXT_1, 148))
    y += s(33)

    f_tag = fonts.get(13)
    tag = _ellipsis(d, title, f_tag, s(330))
    thw = d.textlength(tag, font=f_tag) + s(28)
    _arounded(card, (ix, y, ix + thw, y + s(27)), s(999),
              fill=(*A_ACCENT, 33), outline=(*A_ACCENT, 191), width=1)
    d = ImageDraw.Draw(card)
    d.text((ix + s(14), y + s(7)), tag, font=f_tag, fill=(*A_ACCENT_2, 255))
    y += s(27 + 16)

    f_score = fonts.get(52, bold=True)
    f_unit = fonts.get(12)
    score_txt = str(score)
    d.text((ix, y), score_txt, font=f_score, fill=(255, 255, 255, 255))
    d.text((ix + d.textlength(score_txt, font=f_score) + s(12), y + s(30)),
           '好感度 / AFFECTION', font=f_unit, fill=(*A_TEXT_1, 117))
    y += s(60)
    f_rel = fonts.get(13, bold=True)
    rel_line = '关系 ' + rel + ('（唯一）' if uniq else '')
    d.text((ix, y), _ellipsis(d, rel_line, f_rel, iw),
           font=f_rel, fill=(*A_GOLD, 255))

    # ---- 引文框（对应 denia_core 的 DENIA'S COMMENT）
    cy = main_y + s(_A_MAIN) - s(18)
    cb_x0, cb_x1 = PAD, W - PAD
    ch_y1 = cy + comment_h
    _arounded(card, (cb_x0, cy, cb_x1, ch_y1), s(10), fill=(0, 0, 0, 71))
    d = ImageDraw.Draw(card)
    d.rectangle((cb_x0, cy + s(8), cb_x0 + s(4), ch_y1 - s(8)), fill=(*A_ACCENT, 255))
    d.text((cb_x0 + s(6), cy + s(4)), '"', font=fonts.get(32, bold=True),
           fill=(*A_ACCENT, 107))
    _aspaced(d, (cb_x0 + s(28), cy + s(17)), "FAVOUR PROFILE",
             fonts.get(10), (*A_ACCENT_2, 148), 2)
    ty = cy + s(17 + 10 + 8 + 5)
    for ln in sum_lines:
        d.text((cb_x0 + s(28), ty), ln, font=f_sum, fill=(*A_TEXT_1, 235))
        ty += s(26)

    # ---- 分隔线 + 段标题
    y = ch_y1 + s(18)
    d.line([(PAD, y), (W - PAD, y)], fill=(*A_ACCENT, 56), width=1)
    y += s(13)
    d.rounded_rectangle((PAD, y, PAD + s(4), y + s(12)), radius=s(3),
                        fill=(*A_ACCENT, 255))
    _aspaced(d, (PAD + s(11), y - s(1)), 'DETAIL // 好感度详情',
             fonts.get(11, bold=True), (*A_ACCENT_2, 255), 2)

    # ---- 三联统计
    y += s(12 + 12 + 8)
    gap = s(10)
    bw3 = (W - PAD * 2 - gap * 2) // 3
    f_num = fonts.get(25, bold=True)
    f_lbl = fonts.get(10)
    stat_h = s(_A_STAT)
    cells = [(rank, '当前排名'),
             (_ellipsis(d, level, f_num, bw3 - s(12)), '当前等级'),
             ('是' if uniq else '否', '唯一关系')]
    for i, (num, lbl) in enumerate(cells):
        x0 = PAD + i * (bw3 + gap)
        _arounded(card, (x0, y, x0 + bw3, y + stat_h), s(10),
                  fill=(*A_TEXT_1, 14), outline=(*A_ACCENT, 56), width=1)
        d = ImageDraw.Draw(card)
        d.text((x0 + bw3 / 2, y + s(12)), num, font=f_num,
               fill=(*A_ACCENT_2, 255), anchor='ma')
        d.text((x0 + bw3 / 2, y + s(12 + 25 + 5)), lbl, font=f_lbl,
               fill=(*A_TEXT_1, 110), anchor='ma')

    # ---- 两格详情
    y += stat_h + s(16)
    gap2 = s(12)
    sw2 = (W - PAD * 2 - gap2) // 2
    f_slbl = fonts.get(10, bold=True)
    f_sval = fonts.get(15, bold=True)
    f_ssub = fonts.get(11)
    stat_h2 = s(_A_STATUS)
    span = (max_f - min_f) or 1
    pct = min(100, max(0, round((score - min_f) / span * 100)))
    for i in range(2):
        x0 = PAD + i * (sw2 + gap2)
        _arounded(card, (x0, y, x0 + sw2, y + stat_h2), s(10),
                  fill=(*A_TEXT_1, 14), outline=(*A_ACCENT, 56), width=1)
        d = ImageDraw.Draw(card)
        tx = x0 + s(14)
        if i == 0:
            d.text((tx, y + s(12)), '◆ 好感度水位', font=f_slbl, fill=(*A_TEXT_1, 112))
            d.text((tx, y + s(29)), f'{score} 好感度', font=f_sval, fill=(*A_ACCENT_2, 255))
            bar_y = y + s(53)
            d.rounded_rectangle((tx, bar_y, x0 + sw2 - s(14), bar_y + s(4)),
                                radius=s(3), fill=(*A_ACCENT, 51))
            if pct > 0:
                fw = max(s(4), int((sw2 - s(28)) * pct / 100))
                fill_img = vgrad(fw, s(4), [(0.0, A_ACCENT), (1.0, A_GOLD)]).convert('RGBA')
                fmask = Image.new('L', fill_img.size, 0)
                ImageDraw.Draw(fmask).rounded_rectangle(
                    (0, 0, fw - 1, s(4) - 1), radius=s(3), fill=255)
                fill_img.putalpha(fmask)
                card.alpha_composite(fill_img, (tx, bar_y))
                d = ImageDraw.Draw(card)
            d.text((tx, y + s(62)), f'下限 {min_f}｜上限 {max_f}　·　{pct}%',
                   font=f_ssub, fill=(*A_TEXT_1, 122))
        else:
            d.text((tx, y + s(12)), '◆ 最近互动', font=f_slbl, fill=(*A_TEXT_1, 112))
            d.text((tx, y + s(29)),
                   _ellipsis(d, last_t, f_sval, sw2 - s(28)),
                   font=f_sval, fill=(*A_ACCENT_2, 255))
            d.text((tx, y + s(62)), _ellipsis(d, '首次记录 ' + created, f_ssub, sw2 - s(28)),
                   font=f_ssub, fill=(*A_TEXT_1, 122))

    _afooter(card, fonts, footer)
    _aseal(card)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    card.convert('RGB').save(out_path, 'PNG')
    return out_path