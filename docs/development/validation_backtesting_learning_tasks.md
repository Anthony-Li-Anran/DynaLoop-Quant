# Validation & Backtesting — 验收规格（S1–S4）

> **2026-11-09 状态更新**：按 Anthony 要求，`AGENTS.md` 已改为「AI 全权负责」，以练促学制度废止。本文件保留为**验收规格与一手依据索引**，不再作为分派给 Anthony 的练习清单。引擎 S1–S4 已全部实现并集成进 `src/dynaloop/validation_backtesting_engine/`；对应断言已转为 `tests/test_validation_backtesting_learning_tasks.py` 中的正式测试（26 条，全部通过）。下文「归属」「集成顺序」等段落为历史记录。
>
> **架构口径范围纠正（2026-11-09 第三次，Anthony 原话「各模块内的功能高度解耦，但是作为服务整体要能直接拼接联系！你理解错了！」）**：本文件中「不形成依赖链」「跨模块类型对齐一律由接入方适配」「不得为回测去修改 Data 模块」等**跨模块**旧句一律停止适用，已在对应条目就地标注；「模块内高解耦 / 自带简单输入契约 / 泛化 / 统计归统计引擎」等结论继续有效。权威口径见 `AGENTS.md` §1.9。

原说明：本文件**只写规格与验收标准，不含实现、不含解法**。

## 0. 已完成的机械层（本轮交付）

| 位置 | 内容 |
|---|---|
| `src/dynaloop/validation_backtesting_engine/run_configs.py` | `RunConfigRecord` / `RunConfigStore`：用户自定义回测配置的 JSON 持久化（纯 CRUD） |
| `src/dynaloop/interaction/api.py` | `GET/POST/GET/PUT/DELETE /api/backtests/configs`；`app.state.run_config_store` |
| `frontend/src/pages/BacktestsPage.tsx` | 选数据集/版本/标的、设窗口/本金/策略类与参数、保存与回放配置、结果面板占位 |
| `tests/test_validation_backtesting_configs.py` | 记录校验、存储、端点 CRUD 的正式测试 |
| `tests/test_validation_backtesting_learning_tasks.py` | 下述验收用例的 skip 骨架 |

配置层**不解释** `start` / `end` 的单位，不校验交易日历，不实例化策略，不执行任何撮合。这些都是引擎核心，属于下面的练习。

## 1. 模块边界（要求）

- **独立引擎（模块内口径，继续有效）**：自带简单输入契约，自定义策略 + 自选数据即可直接跑回测；引擎核心不把 `Data` / `Experiment Management` / `Statistical & Uncertainty` 等模块的领域类型写进核心。
- **范围纠正（2026-11-09 第三次）**：上一句只是**模块内高解耦**，不是跨模块禁令。旧句「跨模块类型对齐由接入方适配」「不形成依赖链」已停止适用；跨模块协作应直接调用被调用模块的公开接口（回测取数直接联系 Data 模块），并允许在被调用模块内新增公开能力。见 `AGENTS.md` §1.9。
- **全参数化**：标的、时间窗口、本金、策略、撮合语义一律由调用方给，引擎里不得存在「日线 / 单标的 / 某只票 / 某段日期」这类常量。
- **时间轴**：只在有序 bar 序列上推进，只比较 timestamp 先后；`SAME_BAR` / `NEXT_BAR` 是 bar 相对语义，不等于「日」或「下一日开盘」。频率 / 日历 / 时区只是可覆盖的观测元数据，不参与推进。
- **本版只做批量历史回测**：时序推进 → 模拟撮合 → 记账 → 描述性结果与基准对照。不做统计推断（显著性 / 置信度 / 覆盖率 / 多重检验——归统计引擎，且**不为它预留接口**），不碰在线模拟盘，不做收益导向。
- **可复现**：resolved config 快照 + 逐笔成交账本 + 实际运行窗口；Data 的不可变版本只是可选溯源方式。
- **生产路径不许留 stub / TODO / `NotImplementedError`**；练习代码只写进 `practice/validation_backtesting/`。

## 2. 验收命令

```
E:/anaconda/envs/dynaloop/python.exe -m unittest discover -s tests -p "test_*.py" -q
```

练习区用例在核心实现落地前全部 skip；Anthony 实现并经 review 后，由 AI 把验收断言补成真实测试并集成进生产路径。

## 3. 练习清单

### S1 — 事件循环与 PIT 时序

- **归属**：`[Anthony 核心练习]`
- **学习目标**：为什么前视偏差必须由引擎层强制，而不能依赖调用方自觉；对比 qlib `backtest_loop` 的因果推进与 ml4t 的生命周期约束。
- **边界**：`practice/validation_backtesting/engine.py` 单文件、一个函数族。
- **验收标准**：
  1. t 时刻交给策略的视图不含 t+1 及之后的 bar；
  2. 不等间隔的 timestamp 序列也能逐根推进（不假设固定频率）；
  3. `start` / `end` 是调用参数，可省略（省略 = 跑 feed 全量）；窗口外的 bar 不产生交易或权益观测；多段窗口互不影响；
  4. 在 bar N 提交的订单不会在 bar N 成交（默认 `NEXT_BAR`）；
  5. `SAME_BAR` 配置产生前视偏差警告。
  6. `on_prepare` 阶段拿不到 feed 的未来时间戳。
- **概念要点（不展开解法）**：策略可见性由引擎裁剪视图决定，不是策略自己"少看一点"；窗口是 feed 上的视图，不是引擎状态。

### S2 — `Exchange`：撮合语义

- **归属**：`[Anthony 核心练习]`
- **学习目标**：撮合语义为什么必须显式进 `BacktestConfig`；同一策略换 fill timing 后结果就不可比（ml4t 的跨引擎压力测试中同输入下终端值符号相反）。
- **边界**：`practice/validation_backtesting/exchange.py` 单文件；不引入交易日历假设。
- **验收标准**：固定输入的黄金用例，逐笔断言成交时点、成交价源、费用、现金与持仓；至少覆盖拒单与部分成交各一条；`EXIT_FIRST` 订单处理顺序可验证；断言用 bar 序号，不用日期。

### S3 — `Account` / `Position` 记账

- **归属**：`[Anthony 核心练习]`
- **学习目标**：逐笔 fill 账本与权益序列的一致性；mark 价格源与 fill 价格源为什么必须分离。
- **边界**：`practice/validation_backtesting/account.py` 单文件；标的是任意 symbol 集合，用 mapping，不写单标的常数。
- **验收标准**：每根 bar 都成立 `cash + Σ(position × mark) == equity`；买卖各一次后收盘对账零差异；多 symbol 下同样成立。

### S4 — `BacktestConfig` 快照与端到端 `run_backtest`

- **归属**：`[Anthony 核心练习]`
- **学习目标（交叉）**：AI 侧 = infra 的配置快照 / 可复现语义；QUANT 侧 = 回测可复现与数据 vintage 溯源（Data 不可变版本只是**可选**来源）。策略形态照成熟实现：逻辑是代码对象，配置只声明「用哪个类 + kwargs」。
- **边界**：`practice/validation_backtesting/run.py` 单文件，组合 S1–S3；「不新增对其他模块的 import」是当时练习区的单文件边界，已随以练促学制度废止，`MUST NOT` 被读成跨模块连接禁令（见 `AGENTS.md` §1.9）。
- **验收标准**：
  1. 同一份配置跑两次，resolved config 与 fills / equity **逐位一致**；
  2. 换策略类 / 换窗口 / 换本金 / 换标的，引擎代码零改动；
  3. spec 记录实际运行窗口与实际 bar 数；
  4. 从 A-share 数据集（`date/open/close/high/low/volume` 的 JSON-lines）+ 自定义策略 + 自定义本金 + 自定义窗口跑通一次，产出逐笔成交账本。
- **注意**：适配层（Data records → feed）属于调用方，不在引擎内。**2026-11-09 第三次修正**：旧句「不得为回测去修改 Data 模块」已推翻；允许且应当在 Data 模块内新增公开能力支撑拼接（已落地 `data/services/market_data.py`）。

## 4. 集成顺序（要求）

1. Anthony 在 `practice/validation_backtesting/` 实现 S1–S4；
2. AI 渐进提示（每次 1 条、不含完整解法）→ review 与讲解纠正；
3. AI 把通过的实现集成进 `src/dynaloop/validation_backtesting_engine/`，补齐正式测试与文档；
4. 前端 Results 面板接上 fills / portfolio state / 描述性指标。

## 5. 依据（一手来源，2026-11-07 核实）

| 依据 | 来源 | 性质 |
|---|---|---|
| 职责切分 `executor / exchange / account / position / decision / signal / report` | `microsoft/qlib` → `qlib/backtest/`，README 称组件松耦合可独立使用 | 参照（建议） |
| `BaseStrategy.generate_trade_decision()`；workflow YAML 的 `{class, module_path, kwargs}` + `backtest.{start_time, end_time, account, benchmark}` | `qlib/strategy/base.py`、`examples/benchmarks/XGBoost/workflow_config_xgboost_Alpha158.yaml` | 参照（建议） |
| `Strategy` 子类 `on_start → on_prepare → on_data* → on_end`；`on_data(timestamp, data, context, broker)` | `ml4t/backtest` → `docs/user-guide/strategies.md` | 参照（建议） |
| `BacktestConfig` 无 start/end 字段；`to_spec_dict()` 记录 realized window；`calendar` 可继承 feed 或显式 `None`；`data_frequency` 只是数值约定 | `ml4t/backtest` → `docs/user-guide/configuration.md` | 参照（建议） |
| `NEXT_BAR` / `EXIT_FIRST` / `execution_price` / `commission` / `slippage` 等显式旋钮；`validate()` 对 `SAME_BAR` 警告 | `ml4t/backtest` → `docs/user-guide/execution-semantics.md` | 参照（建议） |
| 逐笔成交账本 `to_fills_dataframe()` 等作为一等产物 | `ml4t/backtest` → `docs/user-guide/results.md` | 参照（建议） |
| 确定性事件时间、订单状态机、回测与模拟盘同一策略代码 | `nautechsystems/nautilus_trader` README | 参照（建议） |
| 统计可信度归统计引擎；引擎不为其预留接口 | Anthony 2026-11-07 纠正 + `AGENTS.md` §1.4 | **要求** |
| 模块内高解耦：独立引擎、自带简单输入契约、内部可独立运行；模块间作为服务整体通过公开接口直接拼接（「不形成依赖链 / 跨模块无依赖」旧口径已停止适用）；「核心第一作者为 Anthony」随以练促学制度废止 | `AGENTS.md` §1.9、Anthony 2026-11-06/07 纠正 + 2026-11-09 第三次范围纠正 | **要求**（按修正后口径） |

未核实 / 待定：具体统计方法不属本模块，无需核实；交叉验证基线是否引入成熟引擎，由 Anthony 另行决定。
