# DynaLoop UI 字体排版规范（Typography）

本规范统一前端所有层级的字体类型与字号。目标：任何一个界面元素都能映射到唯一一级，新增 UI 时先查此表，不要发明新的字号。

**设计原则：阅读优先。** 这是长时间盯着的科研工作台，不是营销页。整体字号从"紧凑"往"舒适"靠：正文 14px，最小不得低于 12px。

## 1. 字体家族

定义于 `src/styles/index.css` 的 CSS 变量，禁止在组件里写其他 font-family。

| Token | 字体栈 | 用途 |
|---|---|---|
| `--font-heading` | "Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif | 所有标题（按字重区分层级） |
| `--font-body` | 同 heading | 正文、UI 控件 |
| `--font-mono` | Consolas, "SFMono-Regular", "Liberation Mono", monospace | 数字指标、ID、版本号、计数 |

**等宽规则**：凡是"标识符/统计数值"（dataset_id、version_id、计数、`21 columns` 这类 meta）一律 mono；叙述性文字一律 sans。

## 2. 字号阶梯（7 级 + 2 特例）

| 级别 | 字号/字重 | 行高 | 颜色 | 对应元素 |
|---|---|---|---|---|
| T1 页面标题 | 26px / 600 | 1.4 | ink | `.page-title`（每页一个） |
| T2 视图标题 | 18px / 600 | 1.5 | ink | 页面内切换视图后的大标题 |
| T3 分组标题 | 16px / 600 | 1.5 | ink | 手风琴抽屉标题、面板内小节标题 |
| T4 面板标题 | 14px / 600 | 1.5 | ink | `.section-title`（Panel 组件标题，全站统一） |
| T5 正文 | 14px / 400 | 1.6 | ink | 说明句、控件文本 |
| T6 表格/标签 | 13px / 500 | 1.5 | muted | 表头（th）、字段标签、次要说明 |
| T7 注释 | 12px / 400 | 1.4 | muted | 脚注、提示、卡片 note |

特例：

| 元素 | 规格 |
|---|---|
| Eyebrow | 11px / 400 / 大写 / 0.12em 字距 / muted |
| 指标数值 | 24px / mono / tabular-nums |

## 3. 使用规则

1. **全局下限 12px**：任何文字不得低于 12px（10px 的 eyebrow 是唯一历史遗留，不再新增）。
2. **层级只降不跳**：相邻容器之间字号逐级变小，靠字重和颜色区分，而不是靠悬殊的字号差。
3. **字重只有两个档**：400（正文）和 600（标题）。不用 500 做标题，不用 700。
4. **颜色只有两个语义**：`ink`（主要内容）和 `muted`（次要/说明/表头）。状态色只用于 StatusBadge 等状态元素。
5. **禁止的新字号**：除上表外不允许出现 15px、17px、20px 等中间值。发现即回改到最近一级。
6. **表格**：单元格 T6（13px），表头同 T6 但颜色 muted、字重 500。

## 4. 落地清单（2026-11-04 应用）

- [x] 手风琴抽屉标题 → T3 16px
- [x] `.section-title`（面板标题）13 → T4 14px
- [x] DataTable 表头/单元格 12 → T6 13px
- [x] MetricCard 标签 12 → 13px，note 11 → T7 12px
- [x] CsvDataOverview 说明文字 12 → T6 13px；meta 计数 mono 12px
- [x] DataPage Operations 说明文字统一 14px 正文
- [ ] 遗留：其余页面遇到低于 12px 或与阶梯不符的字号，按本表即见即改
