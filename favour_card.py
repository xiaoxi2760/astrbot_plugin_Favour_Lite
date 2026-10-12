"""好感度榜单卡片渲染 —— 纯 PIL 本地出图。

视觉沿用 astrbot_plugin_cake_denia 的粉彩玻璃质感（渐变底 + 光晕 + 玻璃泡泡 +
白色圆角卡 + 段位徽章），版式参考 astrbot_plugin_denia_core 的好感度榜单卡
（标题区 → 统计三联 → 段位行 → 页脚）。

本插件没有 denia_core 的那些字段（观察余额 / 自然恢复上限 / 7 次变化柱状图 /
LLM 评价 / 最近变化原因），因此一律不画，不留空位。

payload 字段：
    title        主标题
    subtitle     副标题
    scope        范围 pill 文案（如「当前会话」）
    stats        {"total": int, "max": int, "min": int}
    users        [{"rank", "name", "uid", "favour", "relationship", "is_unique", "title"}]
    footer       页脚文案

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
    f_emo = fonts.emoji(18)
    tw = d.textlength(title, font=f_title)
    draw_emo = f_emo is not None
    if draw_emo:
        ew = d.textlength("\U0001F370", font=f_emo)
        total = ew * 2 + tw + s(26)
    else:
        total = tw
    ty = s(_PAD + 6)
    tx = cx - total / 2
    if draw_emo:
        try:
            d.text((tx, ty + s(2)), "\U0001F370", font=f_emo, fill=(255, 170, 200, 255),
                   embedded_color=True)
            d.text((tx + total - ew, ty + s(2)), "\U0001F370", font=f_emo,
                   fill=(255, 170, 200, 255), embedded_color=True)
        except Exception:
            draw_emo = False
    d.text((tx + (total - tw) / 2 if not draw_emo else tx + ew + s(13), ty),
           title, font=f_title, fill=TITLE_C + (255,))

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