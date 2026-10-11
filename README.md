<div align="center">

# 精简好感度系统 (Favour Lite)

[![上游项目](https://img.shields.io/badge/基于_Favour_Ultra_v4.3.0-ff69b4?style=for-the-badge)](https://github.com/nuomicici/astrbot_plugin_Favour_Ultra)
[![许可证](https://img.shields.io/badge/License-Apache--2.0-blue?style=for-the-badge)](LICENSE)
[![当前版本](https://img.shields.io/badge/当前版本v1.0.0-blue?style=for-the-badge)](#更新日志)

</div>

> [!IMPORTANT]
> **本项目是衍生版，不是原插件。** 基于 [糯米茨/astrbot_plugin_Favour_Ultra](https://github.com/nuomicici/astrbot_plugin_Favour_Ultra) v4.3.0（Apache-2.0）精简修改。
> 原版功能更完整（主动搭话、会话隔离/迁移同步等），需要完整能力请安装 [原版](https://github.com/nuomicici/astrbot_plugin_Favour_Ultra)。

---

## 与原版的差异

- **好感度固定纯全局**：同一用户在所有群聊/私聊共享同一份好感度（原版按适配器隔离会话数据）。
- **移除主动搭话子系统**：定时调度器、合成事件推送等相关代码与配置全部删除。
- **移除会话隔离体系**：会话迁移/同步等功能删除；`_conf_schema.json` 不再提供，全部配置走 WebUI。
- **新增**：LLM 对话结束后在最后一行显示好感度变动（`❤️/🖤：好感度±X  总好感：Y`），并抽成 `favour_change_line()` 供其他插件（如 [astrbot_plugin_cake_denia](https://github.com/xiaoxi2760/astrbot_plugin_cake_denia)）复用。

三轮精简的详细记录（含删改清单与本地提交号）见 [精简修改说明.md](精简修改说明.md)。

---

## 📖 插件概述

为 AstrBot 赋予具备持久记忆的**好感度与人际关系系统**。通过深度集成 LLM、系统指令级覆盖，让 Bot 根据交互历史自然演化与用户的关系（陌生人、朋友、恋人、死敌等）。

**保留的核心特性：**

*   **沉浸式交互与数值隐射**：好感度变化由 LLM 根据对话内容自动判断，默认不可见、静默执行变更。
*   **多维动态关系**：支持单边/双边人际关系确立与解除。
*   **上下文精准注入**：基于 `<FavourDynamicContext>` XML 结构，实时注入好感等级、关系与排他约束，保证人设稳定。
*   **可视化报表与冷暴力惩罚**：图片报表直观展示排行；多次好感度降低触发真实情绪模拟。
*   **SQLite 存储 + 自动备份**：定时备份数据库，WebUI 一键创建/恢复/删除/下载备份。
*   **WebUI 配置面板**：全功能可视化配置与数据管理，支持暗色模式。

---

## 📦 安装

```bash
cd data/plugins
git clone https://github.com/xiaoxi2760/astrbot_plugin_Favour_Lite
# 重启 AstrBot 或重载插件
```

> 💡 从原版 Favour_Ultra 切换过来的用户**数据无需迁移**：数据库与配置目录名保持 `astrbot_plugin_favour_ultra` 不变（见下方「数据存储」），装上即沿用原有好感度数据。

---

## ⚙️ 配置

请在 AstrBot 管理面板的 WebUI 中设置。

#### 1. 基础设置
| 配置项 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `favour_mode` | `galgame` | **判定模式**：`galgame` (易升难降，偏向包容) / `realistic` (拟真/难升易降，严格守卫人设底线)。 |
| `enable_cold_violence` | `true` | **冷暴力开关**：是否启用低好感度惩罚机制。 |
| `min/max_favour_value` | `-100`/`100` | **数值范围**：好感度的上下限。 |
| `default_favour` | `0` | **初始值**：普通新用户的默认好感度。 |

> 好感度为**纯全局模式**：同一用户在所有群聊/私聊共享同一套好感度数据。

#### 2. 高级配置 (`advanced_config`)
| 配置项 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `admin_default_favour` | `50` | **特权初始值**：Bot管理员/特使的初始好感度。 |
| `favour_envoys` | `[]` | **特使列表**：填入用户ID，享受高初始好感度。 |
| `favour_increase_min/max` | `1`/`3` | **上升幅度**：单次互动好感度增加的随机范围。 |
| `favour_decrease_min/max` | `1`/`5` | **下降幅度**：单次互动好感度扣除的随机范围。 |

#### 3. 冷暴力配置 (`cold_violence_config`)
| 配置项 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `consecutive_decrease_threshold` | `3` | **触发阈值**：好感度连续降低次数大于该值触发冷暴力。 |
| `duration_minutes` | `60` | **惩罚时长**：冷暴力持续时间（分钟）。 |
| `replies` | (预设) | **自定义回复**：包含触发时、拦截时、查询时的回复文案。 |

---

## 💻 命令使用手册
- 具体使用方法请使用/好感度帮助查看。

### 1. 通用命令 (所有用户)

| 命令 | 示例 | 描述 |
| :--- | :--- | :--- |
| `查询好感度` | `查询好感度 @某人` | **[文本]** 查询自己或指定用户的详细数据。 |
| `查询当前好感度` | `查询当前好感度` | **[图片]** 生成好感度排行表格。 |
| `好感度指令帮助` | `好感度指令帮助` | 查看详细的指令用法说明。 |

### 2. 管理员命令

> **权限说明**：
> *   **Bot管理员**：配置文件中 `admins_id` 的用户（最高权限）。
> *   **群主**：当前群聊拥有者。
> *   **群管理员**：当前群聊管理员。

| 命令 | 权限 | 描述 |
| :--- | :--- | :--- |
| `修改好感度 <@用户> <数值>` | 群管+ | 强制调整某人的好感度数值。 |
| `修改关系 <@用户> <名称> <1/0>` | 群主+ | 强制修改关系。`1`表示唯一关系(如恋人)，`0`表示非唯一。 |
| `解除关系 <@用户>` | 群主+ | 清除指定用户的所有关系状态。 |
| `清空好感度 <@用户>` | 群主+ | **[慎用]** 清空指定用户的全部数据（需二次确认）。 |

### 3. Bot 管理员专属命令 (全局维护)

| 命令 | 描述 |
| :--- | :--- |
| `查询全局好感度` | **[图片]** 查询全局好感度记录。 |
| `全局修改好感度` | 全局强制调整某人的好感度。 |
| `全局修改关系` / `全局解除关系` | 全局强制修改/解除关系。 |
| `清空全局好感度` | **[极危险]** 清空数据库中所有好感度数据（需二次确认）。 |
| `取消冷暴力` | 强制解除某人的冷暴力锁定状态。 |
| `查看冷暴力列表` | 查看当前处于冷暴力状态的用户。 |

---

## 💾 数据存储

插件采用 **SQLite** 数据库存储数据。

*   **数据库文件**：`data/plugin_data/astrbot_plugin_favour_ultra/favour.db`
*   **自动备份**：默认每 3 小时备份一次，保存在同目录 `backups/` 下，可在 WebUI「备份」Tab 管理。

> 目录名刻意保持 `astrbot_plugin_favour_ultra`，从原版切换过来时数据无缝沿用；请勿手动改名，否则会被视为全新数据库。

---

## 🙏 致谢

- **原项目**：[nuomicici/astrbot_plugin_Favour_Ultra](https://github.com/nuomicici/astrbot_plugin_Favour_Ultra) by [糯米茨](https://github.com/nuomicici)（Apache-2.0）。本项目全部核心能力均来自原项目，向原作者致敬。
- 本仓库由 [xiaoxi2760](https://github.com/xiaoxi2760) 维护，问题反馈请到[本仓库 Issues](https://github.com/xiaoxi2760/astrbot_plugin_Favour_Lite/issues)（与原插件相关的问题也欢迎到[原仓库 Issues](https://github.com/nuomicici/astrbot_plugin_Favour_Ultra/issues)反馈）。

---

## 更新日志

见 [CHANGELOG.md](CHANGELOG.md)（v1.0.0 起为本衍生版记录，v4.3.0 及更早为上游原插件历史）。
