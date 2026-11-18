# DynaLoop-Quant 系统契约表 · 阶段 0

> 2026-11-11 平台审查更新：本文保留阶段交付历史；统计模块不再宣称未经验证的 FWER 保证，当前为经验诊断；代理校准跨轮传递、存储事务与指纹等修复见 [审查报告](platform_audit_2026-11-11.md)。历史测试数字不是当前验收结果。

| 项 | 内容 |
|---|---|
| 日期 | 2026-11-11 |
| 状态 | 阶段 0 交付物（工程契约，讨论稿） |
| 阶段目标 | 让原图六段闭环 + 12 模块端到端可运行、可复现 |
| 本文件性质 | 系统契约表：六段 → 模块映射、逐段输入/输出、模块公开接口清单、调用关系、数据契约、验收判据 |
| 本轮范围 | **仅新增本文档**；`src/`、`tests/`、`frontend/src/`、`AGENTS.md` 均未改动 |
| 依据 | 代码盘点、`AGENTS.md` §1.4 / §1.9 / §1.10 / §1.11、`ARCHITECTURE.md`、`README.md`、`PROJECT.md`、Anthony 2026-11-11 提供的原图与本轮指令 |

**事实分级**（下文中标注）：`[A]` 仓库代码实测；`[B]` 仓库内文档；`[C]` Anthony 原图 / 本轮指令；`[D]` 本文件给出的工程判断，非既定事实。

**状态标记**：`已实现` = 有实现文件与测试；`半成型` = 有定义但缺运行层；`空壳` = 仅 `__init__.py` 一行 docstring；`待建` = 尚未存在的接口或能力。

---

## 0. 定位与边界

### 0.1 为什么先有这张表

`AGENTS.md` §1.9 规定：模块内部高解耦，模块之间作为服务整体**直接拼接**，跨模块协作走被调用方的包级公开接口，不复制逻辑、不另建平行适配层。要把 6 个空壳和 2 个半成型模块接进现有系统，必须先写清「谁调用谁、消费什么、产出什么」，否则会出现重复实现和悬空依赖。

本表不解决「论文主张是什么」「统计工具选哪一套」，`[C]` Anthony 2026-11-11 原话「现在先不写论文！先把整个系统搭建好！」已把论文线整体后置到系统跑通之后。

### 0.2 阶段总完成判据（Anthony 口径，`[C]`）

> 一条命令从真实数据源跑完六段，产出可复现 spec，前后端可见，后端与前端测试全绿；智能组件先以可替换的真实实现接入，不追求一步到位。

当前**不具备**这个入口：Orchestrator 为空壳，六段之间没有任何调度代码（`[A]`）。本文件不声称它已存在，只定义它由哪个模块、在哪个阶段、以什么接口边界补上。

### 0.3 本阶段不做的事

论文主张与 novelty、受控实验的统计设计、统计工具箱选型、GRPO 真训练、扩散 dream 生成合成数据、Jev 是否保留。这些**不是阶段 1–5 的开工门槛**，只作为可替换位预留。

---

## 1. 全局口径

### 1.1 原图六段（`[C]`，据 2026-11-11 项目日志逐字记录）

| 段 | 名称 | 图内组成 |
|---|---|---|
| ① | LLM with GRPO | Small LM + GRPO Post-Training → Exploration Policy（Generation / Search / Evaluation） |
| ② | Factor Discovery | Factor Generation（Natural Language / Code）→ Evaluation & Screening → Candidate Factors `f1..fN` |
| ③ | Sleep · Simulated Exploration / Learned Backtest Proxy | Market Dynamics Proxy → Conformal Calibration → Fast Simulated Estimations（Reward & Uncertainty） |
| ④ | Wake · Real-world Validation | Real Market Data → Backtesting Engine（Realistic Trading Constraints）→ Out-of-sample Performance |
| ⑤ | Joint Adaptation and Update | Model Update / Exploration Strategy Update / Proxy Model Update 三者互连；③→⑤ 为 `Simulation Feedback (Model Bias, Uncertainty)`，④→⑤ 为 `Real-world Feedback (Performance, Distribution Shift)` |
| ⑥ | Statistical Validation | Multiple Testing Correction / Conformal Prediction / Robustness Analysis → Reliable Alpha Factors；`Statistical Feedback (Reliability, New Directions)` 回流 ① |

### 1.2 12 模块目录与现状（`[A]` 阶段 0 盘点快照，2026-11-11，保留原始事实）

正式名见 `ARCHITECTURE.md`（`[B]`）；目录名以 `src/dynaloop/` 实际路径为准。

| # | 正式名 | 目录 | 状态 | 实现文件 / 行数 |
|---|---|---|---|---|
| 1 | Interaction | `interaction` | 已实现 | 2 / 1516 |
| 2 | Orchestrator | `orchestrator` | 空壳 | 0 / 1 |
| 3 | Infrastructure | `infrastructure` | 半成型 | 4 / 385 |
| 4 | Market Environment | `market_environment` | 半成型 | 1 / 185 |
| 5 | Data | `data` | 已实现 | 19 / 8049 |
| 6 | Model | `model` | 空壳 | 0 / 1 |
| 7 | Training Engine | `training_engine` | 空壳 | 0 / 1 |
| 8 | Inference Engine | `inference_engine` | 空壳 | 0 / 1 |
| 9 | Research Engine | `research_engine` | 空壳 | 0 / 1 |
| 10 | Validation & Backtesting Engine | `validation_backtesting_engine` | 已实现 | 11 / 2046 |
| 11 | Statistical & Uncertainty Engine | `statistical_uncertainty_engine` | 空壳 | 0 / 1 |
| 12 | Experiment Management | `experiment_management` | 已实现 | 6 / 1145 |

> **阶段 1 状态更新（2026-11-11，`[A]`）**：上表是阶段 0 的盘点快照，不作改写。阶段 1 后仅 `research_engine` 状态变化：由「空壳 / 0 文件 / 1 行」变为「已实现 / 9 个实现文件 / 因子表示与评估通路」；`__init__.py` 由一行 docstring 填充为公开接口导出。其余 11 模块状态不变，`validation_backtesting_engine` / `data` / `interaction` / `experiment_management` 生产代码零改动。详见 §10。
>
> **阶段 2 状态更新（2026-11-11，`[A]`）**：上表仍为阶段 0 快照，不作改写。阶段 2 后 `model`（3 文件）、`inference_engine`（2 文件）、`training_engine`（4 文件）由「空壳 / 1 行 docstring」变为「已实现」；`research_engine` 新增 `exploration.py`（`ExplorationPolicy`）并把公开导出补齐。阶段 1 的 9 个实现文件、`data` / `validation_backtesting_engine` / `interaction` / `experiment_management` / `market_environment` / `infrastructure` 与 `frontend/src` **全部零改动**。新增依赖 `deap>=1.4` / `gplearn>=0.4.2` 写入 `pyproject.toml` 并装入项目环境。详见 §11。
>
> **阶段 3 状态更新（2026-11-11，`[A]`）**：上表仍为阶段 0 快照，不作改写。阶段 3 后 `market_environment` 由「半成型 / 1 文件 / 185 行」变为「已实现 / 7 文件」：新增 `registry.py` / `observations.py` / `proxy.py` / `feedback.py` / `runtime.py`，`__init__.py` 由 21 行导出扩充为阶段 3 全量公开接口；`definitions.py` **一行未改**。新增依赖 `arch>=7` 写入 `pyproject.toml` 并装入项目环境。`data` / `validation_backtesting_engine` / `research_engine` / `inference_engine` / `model` / `training_engine` / `interaction` / `experiment_management` / `frontend/src` **全部零改动**；`statistical_uncertainty_engine` 与 `orchestrator` 仍为空壳。详见 §12。

> **阶段 4 状态更新（2026-11-11，`[A]`）**：上表仍为阶段 0 快照，不作改写。阶段 4 后 `statistical_uncertainty_engine` 由「空壳 / 1 行」变为「已实现 / 7 文件」，`orchestrator` 由「空壳 / 1 行」变为「已实现 / 7 文件（含 `__main__` 一条命令入口）」；`infrastructure` 新增 `scheduling.py` 并扩充 `__init__.py` 导出，既有 `config.py` / `logging.py` / `resources.py` / `runtime.py` **零改动**。`statistical_uncertainty_engine` 默认方法按 Anthony 2026-11-11 纠正「别死磕 CP，最重要的是最合适」改为**序列相关稳健的块重采样 + max-statistic stepdown**；共形预测降级为可选对照、不默认启用、不宣称覆盖率保证；statsmodels BH-FDR 也只作「独立假设基线对照」。新增依赖 `statsmodels>=0.14` / `scipy>=1.11` 写入 `pyproject.toml`（环境已由 `arch` 顺带安装）。Data / 回测 / Research / Model / Inference / Training / Market Environment / Interaction / Experiment Management / 前端**全部零改动**。详见 §13。

> **阶段 5 状态更新（2026-11-11，`[A]`）**：上表仍为阶段 0 快照，不作改写。阶段 5 后 `interaction` 由「已实现 / 闭环页未开工」变为「已实现 / 闭环状态页已建」：新增 `interaction/loop_store.py`（`LoopRunStore` 落盘完整 trace）与 `api.py` 三个路由（`POST /api/loop/runs` / `GET /api/loop/runs` / `GET /api/loop/runs/{fingerprint}`，`LoopRunPayload` 冻结全参数），前端新增 `pages/LoopPage.tsx`（六段 `StageRecord` + `StatisticalFeedback` 可视化）与 `/loop` 导航项。六段逻辑完全复用阶段 4 的 `LoopOrchestrator`，`interaction` 只做编排与呈现。`data` / 回测 / Research / Model / Inference / Training / Market Environment / Statistical & Uncertainty / Orchestrator / Experiment Management / 前端生产代码**全部零改动**。后端新增 6 条 `tests/test_loop_api.py`，`States.test.tsx` 同步导航项。实跑：后端 **472 tests**、前端 **38 tests**、`tsc -b` / `compileall` 干净、`frontend/src` CJK = 0、无 stub / TODO。详见 §14。

前端：`frontend/src/pages/` 下 8 个页面，路由定义在 `frontend/src/app/router.tsx`（`/`、`components`、`data`、`data/datasets/:datasetId/preview`、`backtests`、`experiments`、`runtime`、`settings`）；API 客户端类型与 `api` 对象在 `frontend/src/features/api.ts`（`[A]`）。

### 1.3 必须沿用的既有约束

- **模块间直接拼接**：调用方直接 `import` 被调用模块 `__init__.py` 导出的公开类型 / facade / service，不建平行适配层（`AGENTS.md` §1.9，`[B]`）。
- **回测引擎不改**：核心只收有序 bar records，只比较 timestamp 先后；策略逻辑是代码对象，配置只选类 + kwargs；撮合语义（commission / slippage / `fill_ordering` / `SAME_BAR` 等）显式进 `BacktestConfig`（`[A]`，`[B]` README §Validation & Backtesting）。
- **统计可信度归统计模块**，回测只产出确定性结果、不预留统计契约（`[B]` `AGENTS.md` §1.9 第 4 条 + README）。
- **数据契约**：源声明自己的列与 `frequency_options`，注册即用；`tape` / `panes` / `view_config` 是旁路，不进 `resolved config` / `spec`（`AGENTS.md` §1.11，`[B]`）。
- **界面文案全英文**、`frontend/src` CJK = 0、涨红跌绿、¥（`AGENTS.md` §1.10，`[B]`）。
- **无 stub / TODO / 空实现**，测试与构建实际跑过；改既有代码先说明理由并等确认（`AGENTS.md` §1.5 / §1.8，`[B]`）。
- Python 一律用 `E:\anaconda\envs\dynaloop\python.exe`；前端依赖本地 `npm` 安装（`AGENTS.md` §2 / §3，`[B]`）。

### 1.4 相位与单位语义（工程口径，`[C]` + `[D]`）

| 项 | 口径 |
|---|---|
| 发现单位 | **一个因子候选**；一批候选构成检验族。不是逐 bar 动作，也不是一条净值曲线 |
| Sleep | 代理回测给出 reward 与 uncertainty 的**快速估计**，不是生成合成训练数据 |
| Wake | 真实数据 + 确定性回测引擎，外生裁决 |
| reward | 回路内的训练信号；**不是系统成功判据** |
| 周期词汇 | 规范周期 id `1m/5m/15m/30m/60m/1d/1w/1M` 是回测层唯一词汇，由源声明 `frequency_options` 推导（`[A]`） |

### 1.5 冻结锚与可更新项（工程默认，`[D]`，阶段 3 落地）

原图 ⑤ 会更新模型、探索策略、代理模型，⑥ 的 Statistical Feedback 会回流改探索方向；唯一外生锚是 ④ 的真实数据 + 确定性回测（`[C]`）。因此工程上分两类：

- **冻结（只读取，回路不得改写）**：数据快照与窗口、因子评估口径、回测 `resolved_config` 与撮合语义、Wake 裁决规则、`spec` / `fingerprint` 计算。
- **可更新**：候选生成分布、探索策略、代理参数、模型权重、统计描述量。

判据：代理与统计模块对冻结项**只有读接口**；任何写回必须产出新版本 / 新 `run_id`，不覆盖既有结果。此条是工程约定，不是论文主张，也不作为开工门槛。

---

## 2. 六段 → 模块映射与输入 / 输出契约

> 「现有可复用公开接口」一栏均为 `[A]` 实测存在的名字；「缺口」一栏是阶段 1–5 待建能力，名称在开工时按一手调研确定，本表不预先造名。

### ① LLM with GRPO（探索策略）

| 项 | 内容 |
|---|---|
| 涉及模块 | `model`（**阶段 2 已实现**）、`training_engine`（**阶段 2 已实现**）、`inference_engine`（**阶段 2 已实现**）、`research_engine`（探索策略 **阶段 2 已补**） |
| 输入 | 上一轮的 Statistical Feedback / 评估值（首轮为种子配置） |
| 输出 | Exploration Policy（Generation / Search / Evaluation）→ 候选族采样请求 |
| 现有可复用 | `build_strategy` / `STRATEGY_REGISTRY`（同属「逻辑是代码对象」口径）、`Infrastructure.load_settings`、阶段 1 `FactorEvaluation` / `FactorCandidate` / `parse_expression` |
| 缺口 | **已补齐（阶段 2）**：`CandidateGenerator` 协议 + DEAP/gplearn 类型化 grammar 实现 + Alpha158 模板族、`SamplingRequest` / `InferenceEngine.sample` / `CandidateBatch`、`ExplorationPolicy`、`factor_reward` / `group_advantages` / 两种 `PolicyUpdater`。GRPO 真训练（模型权重、per-token KL）仍是可替换位，不在阶段 2 范围 |
| 补齐阶段 | 阶段 2 已完成（验收见 §7.5 / §11） |

### ② Factor Discovery

| 项 | 内容 |
|---|---|
| 涉及模块 | `research_engine`（空壳）；取数走 `data`，评估走 `validation_backtesting_engine` |
| 输入 | 候选生成请求、Data 的 bar records |
| 输出 | 受限 DSL 表达式 → 数值序列 → 评估值（IC / RankIC + 回测指标）→ Candidate Factors `f1..fN` |
| 现有可复用 | `data.fetch_bar_records(...)` → `(rows, metadata)`；`validation_backtesting_engine.backtest_from_records(...)` / `run_backtest(...)` / `StaticFeed.from_records(...)` / `BaseStrategy` / `build_strategy(spec, kwargs)`（支持 `module.Class`）；`BacktestResult.metrics` |
| 缺口 | **已补齐（阶段 1）**：`parse_expression` / `evaluate_expression` / `FactorCandidate` / `compile_factor` / `FactorEvaluation`；探索策略（① / ⑤）仍属阶段 2 |
| 补齐阶段 | 阶段 1 已完成（全系统共同语言，优先级最高）；验收见 §7.4 / §10 |

### ③ Sleep · Simulated Exploration / Learned Backtest Proxy

| 项 | 内容 |
|---|---|
| 涉及模块 | `market_environment`（阶段 3 已实现，registry + runtime 承载 simulated 环境）、`statistical_uncertainty_engine`（阶段 4 已实现，消费候选族并给**族级 FWER 控制的统计反馈**：描述性 reliability 复合量 + FWER 控制的 stepdown 选择，CP 覆盖不宣称） |
| 输入 | 冻结窗口、候选因子、来自 ④ 的真实评估值（用于校准代理偏差） |
| 输出 | Fast Simulated Estimations：reward + uncertainty 快速估计；`Simulation Feedback (Model Bias, Uncertainty)` → ⑤ |
| 现有可复用 | `market_environment.EnvironmentDefinition` / `TimeRange` / `ArtifactReference` / `EnvironmentType.REAL\|SIMULATED`（不可变定义）；`validation_backtesting_engine` 的确定性结果可作校准真值 |
| 缺口 | **已补齐（阶段 3）**：`EnvironmentRegistry` 不可变注册中心、`EnvironmentRuntime` / `RealEnvironment` / `SimulatedEnvironment` / `RuntimeSession` 运行层、只读 `WakeObservation` / `FrozenWindow`、`ResampledBacktestProxy`（arch block bootstrap 快估 + `ProxyCalibration` 版本化）、`BiasInjection` 可注入已知量级 bias、`compare_estimates` / `SimulationFeedback` 偏差度量。阶段 4 后 `statistical_uncertainty_engine` 已消费候选族；按 Anthony 口径**共形校准与覆盖率保证降级为可选对照、不默认启用、不宣称保证**（§13） |
| 补齐阶段 | 阶段 3 已完成（验收见 §7.6 / §12） |

### ④ Wake · Real-world Validation

| 项 | 内容 |
|---|---|
| 涉及模块 | `data`（已实现）、`validation_backtesting_engine`（已实现）、`experiment_management`（已实现，记录每轮结果）、`interaction`（已实现，结果可见） |
| 输入 | 真实市场数据（源 key / symbol / start / end / frequency / adjust）、`BacktestConfig`、策略对象 |
| 输出 | Out-of-sample Performance：`BacktestResult.to_dict()`（`resolved_config` / `spec` / `orders` / `fills` / `portfolio_state` / `metrics` / `benchmark` / `bars`）、`fingerprint()`；`Real-world Feedback (Performance, Distribution Shift)` → ⑤ |
| 现有可复用 | `list_backtest_sources`、`fetch_bar_records`、`run_backtest`、`backtest_from_records`、`run_saved_config`、`BacktestResult`、`RunResultStore`、`RunConfigStore`、`POST /api/backtests/quick-run`、`GET /api/backtests/results/{run_id}` |
| 缺口 | **无**。此段是全链已建成的一段，阶段 3 直接复用，不改写 |
| 补齐阶段 | 已完成（2026-11-10 收尾） |

### ⑤ Joint Adaptation and Update

| 项 | 内容 |
|---|---|
| 涉及模块 | `training_engine`（Model Update）、`research_engine`（Exploration Strategy Update）、`market_environment`（Proxy Model Update）、`orchestrator`（阶段 4 已实现，联合调度）、`experiment_management`（每轮留痕）、`infrastructure`（调度语义） |
| 输入 | ③ 的 Simulation Feedback、④ 的 Real-world Feedback、⑥ 的 Statistical Feedback |
| 输出 | 下一轮的探索策略 / 模型参数 / 代理参数；每轮状态与完整 spec |
| 现有可复用 | `ExperimentManagementFacade.create_run(experiment_id, configuration_snapshot, ...)` / `start_run` / `complete_run` / `fail_run` / `get_run` / `list_runs`；`Settings` / `load_settings` |
| 缺口 | **阶段 2 已补齐 Model / Exploration Strategy 的单模块更新语义**：`TrainingEngine.update` 产出带版本的 `ExplorationPolicy` 与全参数 `TrainingStep.spec`（含更新前后权重、reward / advantage、候选与评估指纹）；冻结锚只读、旧版本不覆盖。**阶段 3 已补齐 Proxy Model Update 语义**：`RuntimeSession.recalibrate()` 吸收 `SimulationFeedback.model_bias`，产出新版本 `ProxyCalibration`，旧 calibration 不覆盖。**阶段 4 已补齐**：`LoopOrchestrator` 六段多轮状态机与联合更新顺序、每轮 `ExperimentRun` 全参数留痕、⑥ 的 `StatisticalFeedback` 经 `DirectionAdapter` 回流下一轮 ①；`infrastructure.scheduling` 给状态 / 重试 / 停条件语义 |
| 补齐阶段 | 阶段 2 + 3 + 4 已完成（验收见 §7.7 / §13） |

### ⑥ Statistical Validation

| 项 | 内容 |
|---|---|
| 涉及模块 | `statistical_uncertainty_engine`（**阶段 4 已实现**）→ 结果回 `orchestrator`，反馈回 ① |
| 输入 | 一批候选因子的评估值（`ValidationFamily`：冻结 `FactorEvaluation` + 冻结 bar records + Sleep 估计与偏差反馈）、代理 vs 真实偏差 |
| 输出 | 描述性稳健量（IC 稳定性 / 代理偏差与放大 / 区间经验覆盖）、族级经验 p 值、`Statistical Feedback (Reliability, New Directions)` → ① |
| 现有可复用 | `FactorEvaluation.statistics` / `.fingerprint()` / `SimulationFeedback`（确定性输入，引擎零改动）、`arch.bootstrap` / `statsmodels` / `scipy` |
| 缺口 | **已补齐（阶段 4）**：可替换 `UncertaintyMethod` / `CalibrationMethod` 协议 + 默认 `BlockResamplingMethod`（block sign-flip + max-statistic stepdown、横截面量用 arch IID bootstrap）、`EmpiricalResidualCalibrator`、`StatisticalEngine.validate` / `feedback`。**默认 stepdown 提供族级 FWER 控制**（block sign-flip 置换零假设 + max-statistic stepdown，Romano-Wolf / Westfall-Young 口径，无需 iid 假设）；**BH-FDR 提供 FDR 控制但仅作对照**（其 iid/独立假设在自适应回路不成立，故不宣称）；**CP 覆盖率保证刻意不启用、不宣称**；跨轮自适应选择偏差由描述性 reliability 复合量与 flags 承载，不包装为序贯保证 |
| 补齐阶段 | 阶段 4 已完成（验收见 §7.7 / §13） |

---

## 3. 12 模块契约表

字段说明：`被谁调用` / `消费` / `产出` 三列回答阶段 0 的验收问题；`公开接口（现状）` 全部为 `[A]` 实测；`拟新增` 为 `[D]` 工程占位，不代表已定名。

### 3.1 已实现 / 半成型

**Data · `data`（已实现）**
- 原图段：④（供 ② / ③ 取数）
- 公开接口：`DataFacade`（`open_local` / `register_dataset` / `publish_version` / `get_snapshot` / `import_files` / `import_source` / `process` / `check_quality` / `adapter_registries` 等）；`fetch_bar_records(registries, *, source_key, symbol, start, end, frequency, adjust, capability_store, store)`；`list_backtest_sources(store, registries, capability_store)`；`resolve_market_source`；`ApiSourceStore`；`SourceCapabilityStore`；`probe_source` / `get_or_probe` / `source_signature` / `normalize_spec`；`BUILTIN_MARKET_SOURCES`。
- 被谁调用：`interaction/api.py`（quick-run、源注册、reprobe）、② 的因子求值（阶段 1）、③ 的 simulated 环境（阶段 3）。
- 消费：源配置与能力声明 → 原始 bar records；产出：`(rows, metadata)`，metadata 含 `columns` / `request_spec` / `fetch_window` / `resolved_window` / `recent_window` / `frequency` / `controllable` 等。
- 拟新增：无。

**Validation & Backtesting Engine · `validation_backtesting_engine`（已实现）**
- 原图段：④（同时是 ② 评估值、③ 校准真值的来源）
- 公开接口：`run_backtest(feed, strategy, config, *, start, end)`、`backtest_from_records(records, *, symbol, strategy, config, start, end, **feed_options)`、`run_saved_config(record, records_provider, *, start, end)`、`StaticFeed` / `BarView` / `BacktestConfig` / `Bar` / `FillOrdering` / `PriceSource`、`BaseStrategy` / `build_strategy` / `STRATEGY_REGISTRY` / `get_strategy_catalog`、`BacktestResult` / `RunResultStore` / `RunConfigStore`。
- 被谁调用：`interaction/api.py`、② 的因子评估（阶段 1）、③ 的代理校准（阶段 3）、⑥ 的检验族输入（阶段 4）。
- 消费：有序 bar records + 策略对象 + `BacktestConfig` + 窗口 → 产出：`BacktestResult`（`metrics` 含 `total_return` / `max_drawdown` / `turnover` / `sharpe_ratio` / `annualized_volatility` / `bar_count` / `fill_count` / `rejected_count` / `reconciliation_max_abs` 等）。
- 拟新增：**无**。引擎一行不改；因子编译成的策略类实现 `BaseStrategy` 生命周期即可接入。

**Interaction · `interaction`（已实现）**
- 原图段：贯穿（结果可见 / 状态可见）
- 公开接口：`create_app(data_facade=..., experiment_facade=..., source_adapter_registry=..., format_adapter_registry=...)`；`panes.py` 的 `build_panes(rows, timestamps, columns)` / `default_view_config(panes)` / `normalise_view_config(...)` / `align_tape(...)`；路由含 `POST /api/backtests/quick-run`、`GET /api/backtests/sources`、`GET /api/backtests/results/{run_id}`、`PUT /api/backtests/results/{run_id}/view-config`、`POST /api/data/api-sources`、`POST /api/data/api-sources/{key}/reprobe` 等（完整清单见 `api.py`）。
- 注意：`interaction/__init__.py` 目前只有一行 docstring，实际公开入口是 `interaction.api.create_app` 与 `interaction.panes`（`[A]`）。
- 被谁调用：前端 `frontend/src/features/api.ts`；阶段 5 新增闭环状态页。
- 消费：各模块公开接口的返回值 → 产出：HTTP JSON + 前端页面（全英文）。
- **阶段 5 已实现**：`POST /api/loop/runs` / `GET /api/loop/runs` / `GET /api/loop/runs/{fingerprint}`（`LoopRunPayload` 冻结全参数，`source_key` 选真实冻结窗口、缺省用显式标注的合成 demo bars），`LoopRunStore` 落盘完整 trace；前端 `pages/LoopPage.tsx` 渲染六段 `StageRecord` 与 `StatisticalFeedback`，导航加 `/loop` 入口。六段逻辑完全复用阶段 4 的 `LoopOrchestrator`，`interaction` 只做编排与呈现。

**Experiment Management · `experiment_management`（已实现）**
- 原图段：贯穿（可复现研究的判断层）
- 公开接口：`ExperimentManagementFacade`（`open_local` / `create_experiment` / `create_run` / `start_run` / `complete_run` / `fail_run` / `cancel_run` / `get_run` / `get_result` / `list_runs`）；`Experiment` / `ExperimentRun` / `ExperimentResult` / `ExperimentLifecycleService` / `ExperimentRepository`。
- 被谁调用：`interaction/api.py`；阶段 4 由 Orchestrator 为每轮 wake/sleep 创建 run。
- 消费：`configuration_snapshot`（每轮完整 spec）→ 产出：带状态的 run 与 result 记录。
- 拟新增：无。

**Infrastructure · `infrastructure`（半成型）**
- 原图段：贯穿
- 公开接口：`Settings` / `load_settings` / `ConfigurationError`；`RuntimeInfo` / `get_runtime_info`；`ResourceSnapshot` / `get_resource_snapshot`；`configure_logging` / `get_logger`。
- 被谁调用：`interaction/api.py`（`/api/runtime`、`/api/settings`）；阶段 4 Orchestrator 用它做配置快照与环境记录。
- 消费：配置文件 / 系统状态 → 产出：不可变配置对象、运行时与资源快照、日志器。
- 拟新增：训练 / 推理链路的接口边界与调度语义（`AGENTS.md` §1.4 归给本模块，目前未落地），阶段 4 补齐时点。

**Market Environment · `market_environment`（阶段 3 已实现）**
- 原图段：③（simulated）、④（real）、⑤（Proxy Model Update）
- 公开接口：`definitions.py` 原有 6 类全部保留且零改动；新增 `EnvironmentRegistry`（`register` / `spec` / `latest` / `references` / `fingerprint`）与 `EnvironmentRegistryError` / `definition_payload`；`FrozenWindow` / `WakeObservation` / `wake_observations` / `factor_group_key` / `require_same_window`；`ProxyConfig` / `BiasInjection` / `ProxyCalibration` / `ResampledBacktestProxy` / `BacktestProxy` 协议 / `ProxyError`；`SimulatedEstimation` / `BiasReport` / `SimulationFeedback` / `compare_estimates`；`RealEnvironment` / `SimulatedEnvironment` / `EnvironmentRuntime` / `RuntimeSession` / `EnvironmentRuntimeError`。
- 被谁调用：阶段 3 目前由测试与后续阶段 4 的 Orchestrator 直接拼接；`Interaction` / 前端仍零引用（阶段 5 才接入页面）。
- 消费：阶段 1 `FactorEvaluation` 的只读真值 + 候选族 + 可注入 bias → 产出：`SimulatedEstimation`（reward / uncertainty / 描述性区间）、`SimulationFeedback`（`model_bias` / `amplification`）、新版本 `ProxyCalibration`、全参数 `RuntimeSession.spec()` 与 `run_id`。
- 阶段 3 落地：注册中心拒绝覆盖冻结定义；Wake 只读、不重跑回测；`arch` block bootstrap 给快估不确定性；recalibrate 只产新版本。详见 §12。

### 3.2 空壳 6 个

| 模块 / 目录 | 原图段 | 现状 | 被谁调用（目标） | 消费 → 产出 | 补齐阶段 |
|---|---|---|---|---|---|
| `model` | ① | **已实现（阶段 2）** | `inference_engine` / `training_engine` | `CandidateGenerator` 协议 + `GrammarCandidateGenerator`（DEAP 类型化树 / gplearn 函数集）+ `TemplateCandidateGenerator`（Alpha158 模板族全空间枚举）；LM 实现直接替换该协议 | **2 已完成** |
| `inference_engine` | ①② | **已实现（阶段 2）** | `research_engine` / `training_engine` | `SamplingRequest` + 冻结 `ExplorationPolicy` + `SeedSequence([seed, round])` → `CandidateBatch`（`f1..fN` 组，spec 全参数） | **2 已完成** |
| `research_engine` | ①②⑤ | **已实现（阶段 1 + 阶段 2 探索策略）** | ① / ③ / ⑥（阶段 2–4 接入） | 受限 DSL 表达式 + bar records → 数值序列 / IC / 回测评估值 / 编译策略；新增 `ExplorationPolicy`（冻结、带版本、唯一可更新项） | **1、2 已完成** |
| `training_engine` | ①⑤ | **已实现（阶段 2）** | `orchestrator`（阶段 4） | `factor_reward`（只读 `FactorEvaluation.statistics`）/ `group_advantages`（TRL 组归一化）/ `RewardWeightedUpdater` + `GRPOGroupUpdater`；`TrainingStep.spec` 每轮留痕；**只做单步更新语义** | **2 已完成**（多轮调度属 4） |
| `statistical_uncertainty_engine` | ⑥（③ 的代理快估由 `market_environment` 承载，阶段 3 已实现） | **已实现（阶段 4）** | `orchestrator`（阶段 5 再接 `interaction`） | `ValidationFamily` → `StatisticalReport`（默认块重采样 + max-statistic stepdown **提供族级 FWER 控制** / bootstrap 置信区间 / 稳健量）→ `StatisticalFeedback`；CP 与 BH-FDR 是可替换对照（CP 不宣称覆盖；BH-FDR 假设在回路中不成立故不宣称 FDR） | **4 已完成** |
| `orchestrator` | ⑤（串起六段） | **已实现（阶段 4）** | `python -m dynaloop.orchestrator` / 调用方 | 全部段产物 → 六段多轮状态机 + 每轮全参数 spec + 每轮 `ExperimentRun` 留痕 + ⑥→① 反馈边；同 seed 同指纹 | **4 已完成** |

---

## 4. 跨模块调用关系（拼接图）

### 4.1 已存在的调用（`[A]`）

| 调用方 | 被调用方公开接口 | 载荷 | 产物 |
|---|---|---|---|
| `interaction/api.py` | `data.fetch_bar_records` / `list_backtest_sources` / `probe_source` / `ApiSourceStore` / `SourceCapabilityStore` | 源 key、symbol、窗口、频率 | `rows` + `metadata` |
| `interaction/api.py` | `validation_backtesting_engine.run_backtest` / `build_strategy` / `StaticFeed.from_records` / `BacktestConfig` / `RunResultStore` | `rows` + 策略类 + 配置 + 窗口 | `BacktestResult.to_dict()`、`fingerprint()` |
| `interaction/api.py` | `interaction.panes.build_panes` / `default_view_config` | `rows` + timestamps + columns | `tape` / `panes` / `view_config`（存进 `setup`，不进 spec） |
| `interaction/api.py` | `experiment_management.ExperimentManagementFacade` | experiment / run / result | 实验与运行状态 |
| `interaction/api.py` | `infrastructure.load_settings` / `get_runtime_info` / `get_resource_snapshot` | 配置路径 / 系统状态 | `/api/settings` / `/api/runtime` |
| `frontend/src/features/api.ts` | 上述 HTTP 路由 | JSON | 8 个页面 |

### 4.2 待建的调用（`[D]`，名称开工时定）

```
① Model / Inference ──候选族采样请求──▶ ② Research Engine
② Research ──fetch_bar_records──▶ Data
② Research ──backtest_from_records / build_strategy──▶ Validation & Backtesting
③ Market Environment(simulated) ──读冻结窗口与真实评估值──▶ Data / Validation & Backtesting
④ Wake ──真实数据 + run_backtest──▶ Data / Validation & Backtesting   （已存在，直接复用）
③ / ④ ──Simulation / Real-world Feedback──▶ ⑤ Orchestrator → Training / Research / Market Environment
⑤ ──每轮 configuration_snapshot──▶ Experiment Management
② / ④ / ③ ──候选族 + 评估值 + 代理偏差──▶ ⑥ Statistical & Uncertainty
⑥ ──Statistical Feedback──▶ ①
⑤ / ⑥ ──状态与结果──▶ Interaction（新增闭环状态路由与页面）
Infrastructure ──配置快照 / 日志 / 资源──▶ 全链
```

**阶段 2 已建成的边（`[A]`）**：`inference_engine.InferenceEngine.sample` 直接调 `model.build_generator` / `CandidateGenerator.sample` 与 `research_engine.ExplorationPolicy.probabilities`；`training_engine.TrainingEngine.update` 直接消费 `inference_engine.CandidateBatch` 与 `research_engine.FactorEvaluation`；候选字符串经 `research_engine.parse_expression` 复核。多轮串联仍由调用方（测试或阶段 4 的 Orchestrator）显式驱动，阶段 2 不新增调度模块。

**阶段 3 已建成的边（`[A]`）**：`EnvironmentRuntime.open` 直接消费一批 `research_engine.FactorEvaluation` → `wake_observations`（reward 经 `training_engine.factor_reward` 的唯一入口）→ `RuntimeSession`；`ResampledBacktestProxy.estimate` 直接读 `FactorCandidate.details` 与 `ProxyCalibration`，调 `arch.bootstrap` 的公开 `apply` 产出 `SimulatedEstimation`；`RuntimeSession.feedback` 用 `compare_estimates` 对齐真实与模拟的 `factor_id` 产出 `SimulationFeedback`；`recalibrate` 产新版本 `ProxyCalibration`。**④ Wake 的 `backtest_from_records` 在阶段 3 中一次都没有被调用**（测试用 mock 断言），真实裁决只读阶段 1 已产出的结果。多轮调度与 ⑥ 的 Statistical Feedback 回流在阶段 3 时尚未实现，阶段 4 已补齐（见下）。

**阶段 4 已建成的边（`[A]`）**：`LoopOrchestrator.run` 按 ①→②→④→③→⑤→⑥ 的依赖顺序驱动（Wake 裁决必须先冻结，Sleep 才能拟合代理），每段经 `infrastructure.execute_stage` 记录 `StageRecord`。① 消费上轮 ⑥ 的 `StatisticalFeedback`（`DirectionAdapter` 只产新 `ExplorationPolicy` 版本）；② 调 `InferenceEngine.sample`；④ 调 `FactorResearch.evaluate_batch`（回测引擎与 Data 零改动）；③ 调 `EnvironmentRuntime.open` / `estimate` / `feedback` / `recalibrate`；⑤ 调 `TrainingEngine.update`；⑥ 调 `StatisticalEngine.validate` / `feedback`。每轮 `ExperimentManagementFacade.create_run → start_run → complete_run` 写全参数 spec、metrics 与三类 artifact，重复运行同 seed 幂等不新增 run。`factor_reward` 仍是 reward 唯一入口，`FactorEvaluation` 仍是唯一评估值来源。

原则：以上每条边都走被调用方 `__init__.py` 导出或 facade；不允许在调用方重写数据解析、撮合、指标计算。

---

## 5. 数据契约（贯穿全链的共同语言）

| 层 | 现状 / 定义 | 约束 |
|---|---|---|
| bar records | `data.fetch_bar_records` 返回 `list[dict]`，每根至少 `date/open/high/low/close`，可含 `volume` 与源声明的扩展列（`[A]`） | 源声明驱动，不按厂商字段顺序硬编码；时间戳全程保留时分秒 |
| tape / panes / view_config | quick-run 把原始 `rows` 作为 `setup.tape`，`panes` 由 `build_panes` 生成，`view_config` 存勾选状态（`[A]`） | 旁路，不写进 `resolved_config` / `spec`；切换勾选不重跑引擎 |
| 因子表示与评估值 | **阶段 1 定义** | 受限 DSL 表达式 → 数值序列；GRPO 的 reward、代理的训练样本、统计检验的候选族必须共用**同一份表示与评估值**；NaN / 暖机 / 复权口径显式进 spec |
| resolved config / spec / fingerprint | `BacktestResult.resolved_config` / `spec` / `fingerprint()`（`[A]`） | spec 记录实际运行窗口、bar 数、库版本、feed metadata；`run_id` 由指纹派生 |
| 实验留痕 | `ExperimentManagementFacade.create_run(..., configuration_snapshot=...)`（`[A]`） | 每轮 wake/sleep 的 spec 进 `configuration_snapshot`，不覆盖既有结果 |
| 循环状态 | **阶段 4 已定义**（`LoopConfig` / `LoopSchedule` / `RoundRecord` / `LoopResult`） | 同 seed 同 spec 指纹一致；每轮产物可追溯；运行时机器信息单独放 `LoopResult.environment`，声明 `excluded_from_fingerprint=True`，不进 spec |

---

## 6. 阶段索引与接口预留

本表是**接口归属索引，不是时间排期**；顺序来自依赖关系（`[C]` 上一轮工程蓝图 + `[D]`）。

| 阶段 | 交付 | 新增 / 改动范围 | 依赖 | 验收 |
|---|---|---|---|---|
| **0** | 本契约表 | 仅 `docs/system_contract.md` | 无 | 任一模块都能查到被谁调用、消费什么、产出什么 |
| **1 ✅** | 因子表示与评估通路（**已完成**） | 新增 `research_engine`（9 文件）与 `tests/test_research_engine.py`（33 条）；既有模块零改动 | Data + 回测公开接口 | **已验收**（§7.4）：同一表达式在冻结窗口两次求值逐值一致，评估值与独立引擎运行的 metrics / fingerprint 一致 |
| **2 ✅** | 候选生成 + 采样 + 探索策略 + reward/更新（**已完成**） | 新增 `model`（3 文件）、`inference_engine`（2 文件）、`training_engine`（4 文件）、`research_engine/exploration.py`、`tests/test_stage2_loop.py`（29 条）；新增依赖 `deap` / `gplearn`；既有模块与前端零改动 | 阶段 1 的 `FactorEvaluation` / `FactorCandidate` / DSL 解析器 | **已验收**（§7.5）：同 seed 同 spec 候选族逐值一致，8 轮后分布向高 reward 模板集中，每轮策略参数与指纹进 spec |
| **3 ✅** | Sleep 代理 + Wake 裁决 + 环境运行层（**已完成**） | 扩 `market_environment`（5 新文件 + `__init__.py`）、`tests/test_stage3_environment.py`（35 条）、新增依赖 `arch`；**Wake 复用既有引擎，零改动** | 阶段 1 + 阶段 2 `factor_reward` + 冻结锚 | **已验收**（§7.6）：注入已知量级 bias 后实测 `model_bias` 与注入量逐值一致（`amplification = 1.0`），干净代理偏差为 0，重校准归零；`compare_estimates` 可测代理与真值偏差 |
| **4 ✅** | 统计与不确定性 + 联合更新 + Orchestrator（**已完成**） | 新增 `statistical_uncertainty_engine`（7 文件）、`orchestrator`（7 文件含 `__main__`）、`infrastructure/scheduling.py` 与 `__init__.py` 追加导出、`tests/test_stage4_loop.py`（22 条）；新增依赖 `statsmodels` / `scipy`；既有生产代码与前端零改动 | 阶段 1 / 2 / 3 公开接口 | **已验收**（§7.7）：同 seed 同 spec 指纹与 `run_ids` 一致，每轮 `ExperimentRun` 留痕且 `configuration_snapshot` 与轮 spec 逐字一致，⑥→① 反馈边真实生效 |
| 5 | Interaction 与前端接入 | 新增 API 路由 + 闭环状态页（全英文、CJK = 0） | 阶段 4 | 后端 / 前端测试全绿，页面可打开 |

硬性约束：每阶段完整可跑、无 stub / TODO、测试实际执行；既有代码不静默重写；阶段 1 开工前按 `AGENTS.md` §1.4 先核 Qlib Expression Engine / DataHandler 的一手职责划分，不自创 DSL 命名；阶段 2 开工前核 DEAP `gp.py` / gplearn `functions.py` / TRL `GRPOTrainer` / qlib `Alpha158` 的一手职责划分，并直接引入成熟依赖而不是手写等价实现；阶段 3 开工前核 Gymnasium `registration.py` / `core.py` 与 `arch.bootstrap` 的一手职责划分，并直接引入 `arch` 做时间序列 block bootstrap；阶段 4 开工前核 statsmodels `multipletests` / MAPIE `compute_quantiles` / Prefect `StateType` 的一手口径，并按 Anthony 2026-11-11 原话「要采用合适的统计与不确定性方法和工具，别死磕CP，最重要的是要最合适」把 CP 降为可选对照，主线改用序列相关稳健的重采样。

---

## 7. 验收清单

### 7.1 阶段 0 自身

- [x] 六段 → 12 模块映射（§2）
- [x] 每段输入 / 输出（§2）
- [x] 每模块公开接口清单、被谁调用、消费、产出（§3）
- [x] 跨模块调用关系（§4）
- [x] 数据契约与 spec 口径（§5）
- [x] 每个接口名 / 路由 / 路径经代码核实，无编造（校验记录见 §9）
- [x] 未改动任何生产代码

### 7.2 全系统完成判据（不变，`[C]`）

- [ ] 一条命令从真实数据源跑完六段
- [ ] 产出可复现 spec
- [ ] 前后端可见
- [ ] 后端与前端测试全绿

### 7.3 每阶段门槛（`[B]` `AGENTS.md` §1.5 / §1.8）

- 无 stub / TODO / `NotImplementedError`
- 测试与构建实际跑过（非声称）
- `frontend/src` CJK = 0
- 改既有代码先说明理由并等确认

### 7.4 阶段 1 自身（2026-11-11 实跑）

- [x] 受限 DSL 解析（qlib 算子名 / `$feature` / 中缀 / `ast` 白名单，无 `eval`）
- [x] 35 个算子全部有真实实现，rolling / ewm / corr 直接调 pandas
- [x] PIT 硬约束：未来引用拒绝、因果前缀一致、因子列物化后策略不重算
- [x] 同一表达式在冻结窗口两次求值逐值一致（values / statistics / metrics / fingerprint）
- [x] 评估值与独立 `backtest_from_records` 运行的 `metrics` 和 `fingerprint()` 一致
- [x] spec 记录窗口 / bar 数 / warmup / min_periods / NaN / adjust / frequency / 数据指纹 / 库版本 / 策略与配置指纹
- [x] 编译产物经 `build_strategy` 的 `module.Class` 解析，回测引擎与 Data 模块一行未改
- [x] 源声明驱动列集合，缺列报错、不推算、不编造
- [x] 后端 380 tests、前端 38 tests、`tsc -b` / `compileall` 干净、`frontend/src` CJK = 0
- [x] 无 stub / TODO / `NotImplementedError`；未改动既有生产代码

### 7.5 阶段 2 自身（2026-11-11 实跑）

- [x] `deap>=1.4` / `gplearn>=0.4.2` 写入 `pyproject.toml` 并装入项目环境；DEAP 负责类型化 primitive set 与树生成，gplearn `make_function` 负责函数集 arity / closure 校验
- [x] `CandidateGenerator` 可替换协议 + 两个真实实现（DEAP/gplearn grammar、Alpha158 模板族），`build_generator` 支持注册表与 `module.Class` 路径
- [x] 所有生成字符串经阶段 1 `parse_expression` / `normalize_expression` 复核；窗口参数恒为正整数字面量，无未来引用
- [x] 模板空间由源声明列驱动，缺列模板不生成；全空间 `enumerate_candidates` 确定性可枚举
- [x] `SamplingRequest` + `SeedSequence([seed, round])` → 固定种子候选族逐值一致、不同轮次不同；按 `factor_id` 去重，`realized_group_size` 如实记录
- [x] `ExplorationPolicy` 冻结、带 `version`、softmax + `exploration_floor`；`with_weights` 只产新版本
- [x] `factor_reward` 只读 `FactorEvaluation.statistics`，`uses_pnl=False`；`group_advantages` 与 TRL `(r-mean)/(std+1e-4)` 逐值一致
- [x] 两种 updater 都真实实现且可替换（`beta=0` 的 GRPO 与 Hedge 逐值一致）；`TrainingStep.spec` 记录每轮 reward / advantage / 候选与评估指纹 / 更新前后策略权重与指纹 / 库版本
- [x] **8 轮闭环后平均 reward 最高的模板权重上升且高于最低模板**；每轮 spec 前后指纹衔接
- [x] 冻结锚只读：更新前后 `FactorEvaluation.fingerprint()` / `CandidateBatch.fingerprint()` / 旧 policy 均不变
- [x] 后端 409 tests、前端 38 tests、`tsc -b` / `compileall` 干净、`frontend/src` CJK = 0、新增模块无 stub / TODO

### 7.6 阶段 3 自身（2026-11-11 实跑）

- [x] `EnvironmentRegistry` 拒绝覆盖冻结定义、精确版本查询、`latest` 按注册序、同定义重注册幂等；`definition_payload` 含时间范围与外部产物引用
- [x] `EnvironmentRuntime.make` 按 `EnvironmentType` 返回 real / simulated 实例；`open` 拒绝引用互换与空候选族；混合冻结窗口被拒
- [x] Wake 只读：`FrozenWindow` / `WakeObservation` 从阶段 1 spec 与 `fingerprint()` 拷贝，reward 唯一入口是 `factor_reward`（`uses_pnl=False`）
- [x] **Sleep 全生命周期不调用 `backtest_from_records`**（mock 断言估计 / 反馈 / 重校准三步），回测引擎与 Data 零改动
- [x] `arch>=7`（实装 8.0.0）的 `CircularBlockBootstrap` / `StationaryBootstrap` 公开 `apply(np.mean, reps)` 驱动快估不确定性；残差不足 2 条时如实标记 `bootstrap_applied=False`，不伪造区间
- [x] `BacktestProxy` 协议可替换（测试以另一真实实现替换默认代理并跑通 session）
- [x] 注入 `additive 0.05` → `model_bias = 0.05`、`expected_bias = 0.05`、`amplification = 1.0`；`multiplicative` 按注入前基准值精确可测；干净代理 `model_bias = 0`
- [x] `recalibrate` 产新版本 `ProxyCalibration`（1→2、`bias_offset = -0.05`），旧对象不变、历史可追溯，重校准后偏差归零
- [x] 冻结锚只读：更新前后 `FactorEvaluation.fingerprint()` 逐值不变，注册中心拒绝改写既有定义
- [x] 同 seed 同 spec 估计逐值一致；`run_id` 可复现且对 bias 敏感；spec 记录窗口 / 定义 / proxy config / bias / 候选族 / Wake 观测 / calibration / round_index / 库版本（含 `arch`）
- [x] 后端 444 tests、前端 38 tests、`tsc -b` / `compileall` 干净、`frontend/src` CJK = 0、新增模块无 stub / TODO
- [x] **共形校准、覆盖率保证、显著性与多重检验在阶段 3 未实现且未声明**；阶段 4 已给可替换对照实现，**默认 stepdown 宣称族级 FWER 控制、BH-FDR 对照宣称 FDR 控制（但自适应回路不满足其假设故不宣称）**，CP 覆盖率保证刻意不启用、不宣称

### 7.7 阶段 4 自身（2026-11-11 实跑）

- [x] **方法选型按 Anthony 口径纠正**：默认不是 CP。逐 bar 因子值序列相关 + 一批候选同时筛 → block sign-flip 零分布 + max-statistic stepdown（Westfall–Young / Romano–Wolf 口径，**提供族级 FWER 控制**）；横截面批次量 → `arch.bootstrap.IIDBootstrap` bootstrap 置信区间
- [x] `SplitConformalCalibrator` 仅为可选对照（MAPIE v0.9.1 `compute_quantiles` 的 `((n+1)(1-α))/n` + `method="higher"`），默认关闭，`exchangeability_valid_in_adaptive_loop=False`、`coverage_guarantee=False`
- [x] `IndependentBaselineMethod`（scipy t 近似 + statsmodels `multipletests`）仅作独立假设对照，`assumptions_valid_in_adaptive_loop=False`，测试逐值核对与 `multipletests` 完全一致
- [x] 缺冻结 bar records 时 `SelectionResult.applied=False` / `p_values=None`，不伪造；`ValidationFamily` 拒绝重复因子、未知 choice 与混合冻结窗口
- [x] `StatisticalReport` / `StatisticalFeedback` 全参数进 spec；`reliability` 是描述性复合量（聚合描述性诊断 + **FWER 控制的 stepdown 选择结果**），`within_family_fwer_control=True`、`loop_level_sequential_significance=False`、`coverage_guarantee=False`（CP 覆盖不宣称）
- [x] 六段状态机按 ①→②→④→③→⑤→⑥ 执行，每段 `StageRecord` 含状态 / 指纹 / attempts；失败时 `LoopError.stages` 保留已完成与 FAILED 记录
- [x] 同 seed 两次 `LoopResult.fingerprint()` 与 `run_ids` 逐值一致；`data_fingerprint` 与 Wake 评估指纹跨运行不变
- [x] 每轮 `ExperimentRun` 状态 COMPLETED，`configuration_snapshot == RoundRecord.spec` 逐字一致，metrics 含 `proxy_amplification=1.0`（注入 0.02），artifacts 含 statistical_report / exploration_policy / proxy_calibration；重放幂等不新增 run
- [x] ⑥→① 反馈边真实生效：`applied_keys` 非空、下一轮策略版本递增；`NoOpDirectionAdapter` 对照下版本只按 training 步增长
- [x] `ReliabilityThresholdStop` 提前停止、`RetryPolicy` 重试计数与 `StageFailure.attempts` 可测；`python -m dynaloop.orchestrator` 一条命令产出完整 spec
- [x] 后端 466 tests、前端 38 tests、`tsc -b` / `compileall` 干净、`frontend/src` CJK = 0、新增模块无 stub / TODO

### 7.8 阶段 5 自身（2026-11-11 实跑）

- [x] `POST /api/loop/runs` 返回完整 trace：六段 stage 顺序 `exploration_policy → factor_discovery → wake_validation → sleep_simulation → joint_update → statistical_validation`，`origin` 为 `synthetic-demo` 或 `source:<key>`，`result.rounds` 含每轮 `stages` / `spec` / `run_id`
- [x] 同 payload 两次请求返回**相同 fingerprint 与 run_ids**（可复现、幂等）；`LoopRunStore` 不覆盖既有 trace，只追加新 fingerprint
- [x] `GET /api/loop/runs` 列表含 fingerprint / origin / round_count / final_reliability / run_ids / experiment_id；`GET /api/loop/runs/{fingerprint}` 返回完整 entry，`GET /api/loop/runs/nope` 返回 404
- [x] 未知 `source_key` 返回 422（经 `fetch_bar_records` 抛 `DataNotFoundError` / `DataDefinitionError`），不伪造数据；缺省路径用显式标注的合成 demo bars，不冒充实盘
- [x] 注入 `bias_magnitude=0.05` 流入 `statistical_validation` 段，`statistical_feedback.reliability` 为 float、`flags` 含 `bias_detected`、`new_directions` 非空
- [x] 前端 `LoopPage.tsx` 全英文、规范术语；表单选源 / 符号 / 窗口 / 种子 / 轮数 / bias / 重采样次数；导航新增 `/loop` 且与既有 6 个入口并列；`States.test.tsx` 同步断言
- [x] 后端 472 tests（466 + 6）、前端 38 tests、`tsc -b` / `compileall` 干净、`frontend/src` CJK = 0、Interaction API 与既有模块 / 前端生产代码**零改动**（只新增路由、store、页面、导航项）

---

## 8. 后置项与未定项（不阻塞开工）

| 项 | 状态 | 说明 |
|---|---|---|
| 统计工具最终选型（学术论文级定案） | **仍后置** | 按 Anthony 口径等模型 / 研究循环成形再定；阶段 4 只固定「可替换协议 + 一个对序列相关与自适应筛选合适的默认实现」，未把任何工具定案 |
| 原图 ③ 的 Conformal Calibration 与有限样本覆盖率保证 | **降级为可选对照** | Anthony 2026-11-11「别死磕CP，最重要的是要最合适」：CP 的 exchangeability 在自适应回路不成立，`SplitConformalCalibrator` 默认不启用、不宣称覆盖率；默认 `EmpiricalResidualCalibrator` 只报告经验分位数与观测覆盖 |
| 论文主张与 novelty | 后置 | 本阶段不写论文 |
| GRPO 真训练 / 扩散 dream / Jev 是否保留 | 后置 | 架构留可替换位，不作为阶段 1–5 门槛 |
| 统计在回路中的主次位置（闸门 / 反馈 / 被测量） | **阶段 4 已定为「反馈 + 被测量」，非闸门** | ⑥ 的 `StatisticalFeedback` 只经 `DirectionAdapter` 影响下一轮 ① 的采样偏好，不拦截候选、不改裁决；其中 **stepdown 选择本身宣称族级 FWER 控制**（多重检验把关），但跨轮序贯意义下仍是描述性反馈而非覆盖闸门；闸门语义若要做须另立口径 |
| 「一条命令」入口的具体形态 | **阶段 4 已定义** | `python -m dynaloop.orchestrator`（默认显式标注的合成 demo 数据；`--records` 注入冻结 JSON 快照，`--database` 留痕，`--output` 写完整 spec）；真实在线源通过 `FactorResearch.fetch_records` 由调用方注入 |
| Interaction API 与闭环状态页 | 后置 | 阶段 5；当前后端闭环结果未在前端可见 |

---

## 9. 校验与变更记录

- 2026-11-11：阶段 0 建立本文件。接口名、路由、页面、模块规模均取自当次代码盘点（`[A]`）；六段文字取自 2026-11-11 项目日志中的原图记录（`[C]`）；阶段索引沿用同日工程蓝图。
- 校验方式：逐一核对 §3 / §4 / §5 中出现的公开接口名在对应源码中存在。实测：91 个接口 / 路由 / 指标 / metadata 标识符全部命中源码，14 个引用路径与 12 个模块目录全部存在，无编造名称。本轮仅新增 `docs/system_contract.md` 与追加项目日志，未改动任何既有代码。
- 阶段 0 复核（2026-11-11，本轮实跑）：后端 `unittest discover -s tests` **347 tests OK**（22.1 s）；前端 `tsc -b` 干净、`vitest run` **38 tests passed**（9 个测试文件）；`frontend/src` CJK = 0。与 2026-11-10 基线一致。
- 预览服务：本轮实测后端 8000 与前端 5173 均返回 502（上轮之后已停止），阶段 0 交付不依赖预览服务；需要查看页面时按既有命令重新拉起即可。
- 阶段 1 复核（2026-11-11，本轮实跑）：后端 `unittest discover -s tests` **380 tests OK**（20.7 s，含新增 33 条）；`compileall -q src tests` 干净；前端 `tsc -b` 干净、`vitest run` **38 tests passed**（9 文件）；`frontend/src` CJK = 0；`src/dynaloop/research_engine/` 无 TODO / stub / `NotImplementedError`。
- 阶段 1 接口核实：`build_strategy` 的 `module.Class` 解析、`backtest_from_records`、`fetch_bar_records`、`BaseStrategy.on_data`、`BacktestResult.to_dict()` / `.fingerprint()` / `.metrics` / `.spec` 全部命中现有公开实现；`validation_backtesting_engine`、`data`、`interaction`、`experiment_management`、`frontend/src` 一行未改。
- 阶段 2 复核（2026-11-11，本轮实跑）：后端 `unittest discover -s tests` **409 tests OK**（24.7 s，含新增 29 条）；`compileall -q src tests` 干净；前端 `tsc -b` 干净、`vitest run` **38 tests passed**（9 文件）；`frontend/src` CJK = 0；`model` / `inference_engine` / `training_engine` / `exploration.py` 无 TODO / stub / `NotImplementedError`。`deap 1.4` 与 `gplearn` 已可导入，`pyproject.toml` 已声明。
- 阶段 2 接口核实：`FactorCandidate.from_expression`、`parse_expression` / `normalize_expression`、`OPERATOR_ARITY`、`FactorResearch.evaluate_batch`、`FactorEvaluation.statistics` / `.fingerprint()`、`BacktestResult` 全部命中阶段 1 / 回测引擎现有公开实现；阶段 1 的 9 个实现文件与其余既有模块、前端一行未改。
- 阶段 3 复核（2026-11-11，本轮实跑）：后端 `unittest discover -s tests` **444 tests OK**（18.2 s，含新增 35 条）；`compileall -q src tests` 干净；前端 `tsc -b` 干净、`vitest run` **38 tests passed**（9 文件）；`frontend/src` CJK = 0；`market_environment` 7 文件无 TODO / stub / `NotImplementedError`。`arch 8.0.0` 已可导入，`pyproject.toml` 已声明 `arch>=7`。
- 阶段 3 接口核实：`FactorEvaluation.spec` / `.fingerprint()` / `.candidate.details` / `.compiled.strategy_kwargs`、`factor_reward` / `RewardSpec`、`EnvironmentDefinition` / `TimeRange` / `EnvironmentType`、`arch.bootstrap.CircularBlockBootstrap.apply`、`backtest_from_records`（mock 未调用）全部命中现有公开实现；`definitions.py`、阶段 1 九文件、阶段 2 十文件、Data / 回测 / Interaction / Experiment Management / frontend 一行未改。
- 阶段 4 复核（2026-11-11，本轮实跑）：后端 `unittest discover -s tests` **466 tests OK**（18.3 s，含新增 22 条）；`compileall -q src tests` 干净；前端 `tsc -b` 干净、`vitest run` **38 tests passed**（9 文件）；`frontend/src` CJK = 0；`statistical_uncertainty_engine` / `orchestrator` / `infrastructure/scheduling.py` 无 TODO / stub / `NotImplementedError`。`statsmodels` / `scipy` / `arch 8.0.0` 均可导入，`pyproject.toml` 已显式声明三者。
- 阶段 4 接口核实：`InferenceEngine.sample`、`FactorResearch.evaluate_batch` / `window_records`、`TrainingEngine.update` / `factor_reward`、`EnvironmentRuntime.open` / `RuntimeSession.estimate` / `feedback` / `recalibrate`、`ExplorationPolicy.with_weights`、`ExperimentManagementFacade.create_run` / `start_run` / `complete_run`、`infrastructure.get_runtime_info` 全部命中现有公开实现；Data / 回测 / Research / Model / Inference / Training / Market Environment / Interaction / Experiment Management / frontend 生产代码一行未改，仅 `infrastructure/__init__.py` 追加新模块导出。

---

## 10. 阶段 1 设计与一手依据（2026-11-11）

### 10.1 qlib 源码核实（GitHub 一手，非二手转述）

| qlib 源码 | 核实到的职责 / 命名 | 本模块对应 |
|---|---|---|
| `qlib/data/ops.py` | `OpsWrapper` / `Operators` 按**类名**注册算子；`OpsList` 含 `Ref / Mean / Sum / Std / Var / Max / Min / Med / Rank / Count / Delta / EMA / WMA / Corr / Cov / Abs / Sign / Log / Add / Sub / Mul / Div / Power / Greater / Less / Gt / Ge / Lt / Le / Eq / Ne / And / Or / Not / If`；`Rolling` 用 `series.rolling(N, min_periods=1)`，`N=0` 为 expanding、`0<N<1` 为 ewm | `operators.py` 的 `Operators` 注册器 + 同名 35 算子；`EvaluationPolicy.min_periods=1` |
| `qlib/data/base.py` | `Expression` 把中缀重载为 `Add/Sub/Mul/Div/Power/Gt/...`；`Feature.__str__ = "$" + name`；`load()` 是求值入口；`get_extended_window_size()` 声明所需历史 | `expressions.py` 的 `Node` / `Feature` / `Operator`、中缀映射、`extended_window_size()` |
| `qlib/data/expression_parser.py` | 新版改用 **`ast` 白名单**，只许 `Operators.<name>(...)`，拒绝私有名 / 未知算子 / 任意属性；`ExpressionSyntaxError` | 同样的 `ast` 白名单与同名异常，并额外禁止未来引用 |
| `qlib/data/data.py` | `ExpressionProvider.get_expression_instance` 解析并缓存；`LocalExpressionProvider.expression` 用 `get_extended_window_size()` 扩窗取数 → `expression.load()` → 裁回请求窗口 | `FactorFrame.evaluate()`；所需历史以 `warmup_bars` 写进 spec（差异见 10.3） |
| `qlib/data/dataset/handler.py` | `DataHandler._data` 是 `data_loader.load(...)` 返回并排序后的 DataFrame；表达式列在加载阶段**已物化**，`fetch` / `get_cols` 只做选择，handler 不解析也不现场计算 | `FactorFrame`（只读物化列）与 `FactorValues`（物化因子列）分离；策略只读 `signals` |

**未引入 qlib 依赖**：其表达式求值绑定 bin 数据格式、calendar 与 provider 初始化；本仓库 Data 已按源声明直出 bar records，`pandas>=2.0` / `numpy>=1.26` 已在 `pyproject.toml` 声明。照其职责划分与命名、全部 rolling / ewm / corr 直接调 pandas，不新增依赖、不手写递推（`AGENTS.md` §1.9 / §1.11 第 6 条）。

### 10.2 语言边界与 PIT

- 语法：`$close`、`Ref($close, 5)`、`($close - Mean($close,5)) / Std($close,5)`、`Operators.Ref(...)`；窗口参数必须是字面量数值。未知算子 / 任意 Python / 属性 / 下标 / lambda / 链式比较均拒绝，表达式长度与节点数有上限。
- **因果性**：`Ref(N<0)` 等未来引用直接拒绝；rolling / ewm / corr 只用当前及历史 bar。测试以「追加未来 bar 后历史前缀逐值不变」验证。
- 数值口径：`Greater/Less` 照 qlib 是 maximum/minimum，比较用 `Gt/Ge/Lt/Le/Eq/Ne`；`Log(x<=0)` 与除零产生 NaN，inf 统一转 NaN；布尔算子把非零非缺失视为真、NaN 视为假。
- **披露的不确定性**：`Rank / WMA / EMA / Corr` 用 pandas 等价实现，与 qlib 的 Cython / 自定义实现在 NaN 细节上可能有数值差异；spec 记录 `library_versions` 与算子 schema 版本，换库需重跑而不是复用旧 spec。

### 10.3 冻结锚与工程差异

- 列集合 = 源声明的数值列 ∩ records 实际数值列；缺列报错，不推算、不补齐、不编造。窗口用与 `StaticFeed.window` 相同的字符串比较冻结，不解释时间单位；时间戳重复或空窗口报错。
- NaN 只有 `propagate`（不填充 / 不插值）；`min_periods` 默认 1，可设整窗严格暖机；`adjust` / `frequency` 是观测元数据，不参与计算。
- **与 qlib 的差异（明确披露）**：qlib 会按 `get_extended_window_size()` 扩窗取历史以保证窗口首端值准确；阶段 1 **只在冻结窗口内求值**，因此前 `warmup_bars` 根可能受暖机影响。所需历史量写进 spec，阶段 3 若需扩窗可由 Data 调整 `start` 重算，此时 `data.fingerprint` 同步变化，不会静默混入旧结果。

### 10.4 单一表示与模块拼接

`FactorEvaluation` 是全链唯一取值对象：候选身份、物化因子序列、IC / RankIC、`BacktestResult.metrics` / `fingerprint()` / `spec` 都在这里。阶段 2 的 reward、阶段 3 的代理训练样本、阶段 4 的检验族**只能读它**，不得各自另算一份（§5 数据契约）。编译产物 `CompiledFactor` 是 `strategy_class` + JSON-safe kwargs，经回测引擎公开的 `build_strategy` 的 `module.Class` 路径解析，再由 `backtest_from_records` 裁决；`FactorSignalStrategy` 把固定三动作 `buy / sell / not move` 暴露为纯函数 `action()`。`FactorResearch.fetch_records` 直连 Data 的 `fetch_bar_records`；`evaluate_batch` 让一批候选共用同一冻结 frame。

### 10.5 验收证据

`tests/test_research_engine.py` 33 条：语法与安全、35 算子与 pandas 口径、因果前缀、列声明、窗口冻结、两次求值逐值一致（values / statistics / metrics / fingerprint）、评估值与独立引擎运行一致、spec 全字段、编译策略与三动作、Data 公开接口直连。实跑：后端 380 tests OK、前端 38 tests passed、`tsc -b` / `compileall` 干净、`frontend/src` CJK = 0。

### 10.6 边界（未做，不作为阶段 1 缺口）

以下是**阶段 1 交付时**的边界快照（当前状态见段末收尾更新）：候选生成 / 探索策略 / GRPO 真训练（阶段 2）、Sleep 代理与可注入 bias（阶段 3）、统计工具与 Orchestrator（阶段 4）、闭环页面（阶段 5）；论文主张、统计工具选型、扩散 dream、Jev 去留仍按 §0.3 / §8 后置。**阶段 1 未定义 reward**：只提供共享评估值，reward 定义属阶段 2，且按 §1.4 口径 reward 是训练信号、不是系统成功判据。（阶段 2 收尾更新：候选生成 / 探索策略 / reward / 参数更新已完成；**GRPO 真训练仍后置**。阶段 3 收尾更新：Sleep 代理、环境注册与运行层、可注入 bias 已完成。阶段 4 收尾更新：统计与不确定性模块、Orchestrator 多轮闭环、每轮留痕、一条命令入口均已完成；统计工具最终选型与闭环页面仍后置。）

---

## 11. 阶段 2 设计与一手依据（2026-11-11）

### 11.1 一手核实（GitHub raw + 本地安装 `deap 1.4` / `gplearn`）

| 一手来源 | 核实到的职责 / 精确命名 | 本模块对应 |
|---|---|---|
| DEAP `deap/gp.py` | `PrimitiveSetTyped(name, in_types, ret_type)`；`addPrimitive(primitive, in_types, ret_type, name)` 用 `Primitive(name, args, ret)` 且 `arity = len(args)`；`addTerminal(terminal, ret_type, name)`；`addEphemeralConstant(name, ephemeral, ret_type)` 用 `MetaEphemeral` 在 `generate` 时实例化。`genFull` 的 condition 是 `depth == height`，`genGrow` 加 `depth >= min_ and random.random() < pset.terminalRatio`，`genHalfAndHalf` 用 `random.choice((genGrow, genFull))`；`generate` 以 `random.randint(min_, max_)` 定高、DFS 栈按类型选 primitive/terminal，`Terminal.value` / `Primitive.name` 是渲染入口。**随机性全部来自全局 `random`，没有局部 RNG 或 seed 参数** | `build_primitive_set`、`_typed_generate`、`_render`；`init_depth` / `init_method` / `terminal_ratio` 写进 spec |
| gplearn `gplearn/functions.py` | `make_function(function, name, arity, wrap=True)` 返回 `_Function(function, name, arity)`；校验 `arity`、输出 `shape == (10,)`、零值 / 负值输入的 `np.isfinite` closure；内置 `add/sub/mul/div/max/min/abs/...` 也是同名 + arity 的函数节点 | `function_set()`：35 个 qlib 算子各声明一个 `_Function`，作为 DEAP primitive 的 callable |
| TRL `trl/trainer/grpo_trainer.py` | `advantages = (rewards - mean_grouped_rewards) / (std_grouped_rewards + 1e-4)`；`rewards.view(-1, self.num_generations)` 分组；`self.beta` 是 KL 到 reference model 的系数，**不参与** reward 归一化；`scale_rewards=False` 时只减均值 | `group_advantages`（numpy `ddof=1` 对应 torch 无偏 `std`）、`CandidateBatch` 的 group、`GRPOGroupUpdater.beta` |
| qlib `qlib/contrib/data/handler.py` | `Alpha158.get_feature_config()` 返回 `Alpha158DL.get_feature_config(conf)`，`conf` 里 `price.windows = [0]`、`feature = ["OPEN","HIGH","LOW","VWAP"]`；label 是字符串模板 `"Ref($close, -2)/Ref($close, -1) - 1"` | `FactorTemplate` 的 `str.format` 模板 + `windows` 列表、`available_templates` 全空间枚举。**差异**：qlib 的 label 用负 `Ref`（未来收益），本 DSL 按阶段 1 PIT 规则拒绝未来引用，因此候选模板只用正窗口 |

**依赖直接使用，不手写等价实现**：`deap>=1.4` / `gplearn>=0.4.2` 已写入 `pyproject.toml` 并装入项目环境（Anthony 2026-11-11 原话「这些包你想用就用，想加就加，别约束！」）。此前「不引入 DEAP/gplearn」的判断已撤销。

### 11.2 职责划分、唯一适配与可复现

- **职责**：DEAP 负责类型化 primitive set 与树生成，gplearn 负责函数集声明与 closure 校验，阶段 1 `operators.py` 负责真正的数值求值。**DEAP 树从不执行**；gplearn 的 stand-in callable 对 elementwise 算子是真实 numpy 等价（含 protected `Div` / `Log` / `Power`），对时序算子只声明 arity 与 closure，因为 rolling / ewm / corr 必须由 pandas 在冻结 frame 上计算。
- **唯一适配**：DEAP `generate` 的停止条件只看 height / depth，不看请求类型；我们的 DSL 要求窗口参数是字面量正整数。`_typed_generate` 逐行复刻 DEAP 的 DFS 栈与 condition，仅增加 `type_ is WINDOW → 强制取 terminal`。`WINDOW` 类型用 `addEphemeralConstant` 注册，窗口值在树生成时固定。
- **确定性**：DEAP 依赖全局 `random`，`_seeded_python_random` 用 `getstate` / `setstate` 保存恢复，种子由 numpy `PCG64` 派生；`SamplingRequest.rng()` 用 `SeedSequence([seed, round_index])` 给每轮独立流；ephemeral 用 `functools.partial` 固定窗口值（避免 DEAP 对 lambda 的 pickle 警告）。spec 记录 RNG 算法、熵、库版本与 choice 概率。
- **策略加权**：DEAP 的 `random.choice` 是均匀的，policy 权重通过**重复注册条目**实现（副本数由概率确定性推导，`budget=16`），不修改 DEAP 源码、不复制生成逻辑；`terminalRatio` 仍由 DEAP 自己的 `terms_count` / `prims_count` 计算。

### 11.3 数据契约与冻结锚

- 全链唯一评估对象仍是阶段 1 `FactorEvaluation`；`factor_reward` 只读 `statistics`（默认 `abs(rank_ic)`），`RewardSpec.to_dict()["uses_pnl"] = False`，并显式拒绝 `total_return` 之类 label。`CandidateBatch` 与 `TrainingStep` 都带 fingerprint / 全参数 spec。
- `ExplorationPolicy` 是**唯一可更新项**：冻结 dataclass、带 `version`，`with_weights` 只产新对象。冻结锚（数据窗口、`EvaluationPolicy`、回测配置与撮合语义、Wake 裁决、spec / fingerprint 计算）在本阶段只有读接口；测试验证更新前后 `FactorEvaluation` / `CandidateBatch` / 旧 policy 的指纹逐值不变。
- 多轮调度、每轮 `experiment_management.create_run` 留痕、⑥ 的 Statistical Feedback 回流**未实现**，按 §6 留给阶段 4 的 Orchestrator；阶段 2 提供的是 `TrainingEngine.update` 单步语义。

### 11.4 验收证据

`tests/test_stage2_loop.py` 29 条：gplearn 函数集与 DEAP 类型化 primitive set、生成合法性 / seed 可复现 / 权重改变算子频率、模板空间源声明驱动、注册表与 `module.Class`、概率归一化与冻结版本、采样 spec 与去重、reward 只读评估值、TRL 优势公式逐值对照、两种 updater 与 KL 行为、**8 轮闭环后平均 reward 最高的模板权重上升且高于最低模板**、每轮 spec 前后指纹衔接、冻结锚不被写回。实跑：后端 **409 tests OK**、前端 **38 tests passed**、`tsc -b` / `compileall` 干净、`frontend/src` CJK = 0。

### 11.5 边界与披露（不是缺口，是口径）

- **GRPO 真训练仍后置**：没有模型权重、tokenizer、per-token KL、reference LM；`GRPOGroupUpdater` 只是「组相对优势 + 离散分布 KL-to-prior 惩罚」的可替换实现，`beta` 是离散近似，不等同 TRL 的 `beta * per_token_kl`。
- grammar 采样会自然产生退化表达式（如 `Sub($high,$high)` 恒为 0），阶段 1 的 IC 对零方差列返回 `None`，reward 取 `missing_value`；**不做静默过滤**，因为过滤条件本身是可更新项，会污染冻结锚口径。
- Hedge 乘性更新后按总和归一化，未被本轮采样到的 key 相对权重会上升（被动 exploration），这是算法语义而非实现错误；`exploration_floor` 另外保证每个 key 的最小采样概率。
- reward 按 §1.4 只是回路内训练信号，**不是**系统成功判据；阶段 3 已给出 `model_bias` / `amplification` / `mean_uncertainty` 的可测量接口，统计工具侧的闸门与误纳率仍在阶段 4 定义。

---

## 12. 阶段 3 设计与一手依据（2026-11-11）

### 12.1 一手核实（GitHub raw + 本地 `arch 8.0.0` / `inspect.signature` 实测）

| 一手来源 | 核实到的职责 / 精确命名 | 本模块对应 |
|---|---|---|
| Gymnasium `gymnasium/envs/registration.py` | `registry: dict[str, EnvSpec] = {}` 以完整 id 为键；`register(id, entry_point, kwargs, additional_wrappers, ...)` 写 `registry[new_spec.id]`，同 id 重注册只 warn 后覆盖；`EnvSpec` 字段含 `id / entry_point / kwargs / max_episode_steps / order_enforce / disable_env_checker / additional_wrappers`，`__post_init__` 由 `parse_env_id` 解析 `namespace / name / version`；`make(id, **kwargs)` 用 `load_env_creator("module:Class")`（`importlib.import_module` + `getattr`）构造，再按顺序套 `PassiveEnvChecker` / `OrderEnforcing` / `TimeLimit` / `additional_wrappers`；`spec()` 只做字面查，`find_highest_version` + `_find_spec` 把无版本 id 解析到最新；`EnvSpec.to_json()` 做 JSON-safe 校验 | `EnvironmentRegistry.register / spec / latest / fingerprint`、`EnvironmentRuntime.make` 按 `EnvironmentType` 分派、`definition_payload` 的全参数 spec |
| Gymnasium `gymnasium/core.py` | `Env.step(action) -> tuple[ObsType, SupportsFloat, bool, bool, dict]`；`Wrapper` 包装 `step` / `reset`，`get_wrapper_attr` / `set_wrapper_attr` 向下层转发；`RewardWrapper.step` 保留 obs / terminated / truncated / info，只把 `reward` 换成 `self.reward(reward)`；`Wrapper.spec` 用 `WrapperSpec(name, entry_point, kwargs)` 把 wrapper 变换登记进 spec | `BiasInjection.apply` 只变换代理 reward，底层估计与 Wake 裁决不动；bias 与 calibration 版本都写进 spec |
| `arch.bootstrap`（本地 8.0.0，`arch/bootstrap/base.py` 源码 + `inspect.signature`） | `__all__` 含 `CircularBlockBootstrap` / `StationaryBootstrap` / `MovingBlockBootstrap` / `IIDBootstrap`；构造签名 `(block_size, *args, seed=None, **kwargs)`，**精确参数名是 `seed` 而非 `random_state`**；`reps` 在 `apply(func, reps=1000)` / `var` / `conf_int` 上；`apply` 先在原始数据算 `base`，再对每次重采样调 `func`，返回 `reps × nparam`；`conf_int(..., method="percentile", size=0.95)` 用 `np.percentile`；block bootstrap 保留区块内局部序列相关、区块边界截断长程依赖，`IIDBootstrap` 破坏时间顺序 | `_bootstrap_spread` 用 `CircularBlockBootstrap` / `StationaryBootstrap` + `apply(np.mean, reps)`，`SeedSequence([seed, round])` 派生的 Generator 直接传给 `seed=`；不手写重采样递推 |
| qlib `Alpha158` / TRL `GRPOTrainer`（阶段 2 已核，阶段 3 复用） | 候选结构由源声明列与算子决定；reward 唯一来源是 `FactorEvaluation.statistics` | `factor_group_key`（features + qlib 算子）、`WakeObservation.reward` 经 `factor_reward` |

**未取到的一手（如实披露）**：Sutton 1990 Dyna 原文 PDF（`incompleteideas.net/papers/Dyna-2.pdf`）与 Sutton & Barto 第 8 章页面本轮均返回站点 404；MAPIE `mapie/regression.py`（`main` 与 `v0.9.1`）均 404。因此阶段 3 **不引用** Dyna 原文措辞，也不实现共形有限样本分位数修正；「真实经验校准模型 + 模拟经验给快估」只按 Anthony 原图 ③/④ 的工程语义落地，不作论文级引用。

### 12.2 职责划分与唯一适配

- **模块内高解耦**：`definitions`（不可变身份）/ `registry`（版本登记）/ `observations`（Wake 只读投影）/ `proxy`（快估与校准）/ `feedback`（偏差度量）/ `runtime`（拼接与会话）各自单一职责，彼此只传不可变数据。
- **模块间直接拼接**：直接 `import` 阶段 1 `FactorEvaluation` / `FactorCandidate`、阶段 2 `factor_reward` / `RewardSpec`，不建平行适配层；`arch` 只负责数值重采样。
- **与 Gymnasium 的实质差异**：它默认覆盖同 id 注册，这里**拒绝覆盖**（§1.5 冻结锚要求写回产新版本）。**未引入 gymnasium 依赖**：其 `make` 强制 `gym.Env` 实例与 checker / TimeLimit wrappers，而本项目的「环境」是冻结评估窗口 + 候选族，不是 MDP step 循环；照其命名与职责划分，不硬套类型。
- **与 arch 的适配**：`block_size` / `reps` / `interval_size` 提升为 `ProxyConfig` 并写进 spec；`block_size` 裁剪到残差样本数；残差不足 2 条时如实标 `bootstrap_applied=False`，不伪造不确定性。
- **可替换位**：`BacktestProxy` 是 `runtime_checkable` 协议；默认 `ResampledBacktestProxy` 是完整真实实现，未来可换成任意学习型代理而不改 runtime / feedback。

### 12.3 冻结锚与可更新项（§1.5 落地）

- **冻结只读**：数据快照与窗口、评估口径、回测 `resolved_config` 与撮合语义、Wake 裁决规则、`FactorEvaluation.fingerprint()`、`EnvironmentDefinition`。`RealEnvironment` 不重算；测试以 mock 断言 `backtest_from_records` 在估计 / 反馈 / 重校准三步中零调用。
- **可更新且只产新版本**：`ProxyCalibration`（`version` / `group_rewards` / `residuals` / `bias_offset`）；`RuntimeSession.recalibrate()` 吸收 `SimulationFeedback.model_bias`，旧对象保留在 `calibration_history`。`run_id` 由定义、窗口、config、bias 与 Wake 指纹派生，同 seed 同 spec 一致。
- **受控实验装置**：`BiasInjection(magnitude, mode)` → `SimulationFeedback.model_bias / expected_bias / amplification`。阶段 3 提供「注入已知偏差 → 测出偏差 → 重校准吸收」的测量闭环，阶段 4 的 Orchestrator 才能在此基础上测「回路放大多少、闸门拦住多少」。

### 12.4 验收证据

`tests/test_stage3_environment.py` 35 条：注册表冻结 / 版本 / 幂等 / 载荷，Wake 只读与窗口一致性，配置与 RNG，arch bootstrap 生效与退化不造假，可替换代理，加性与乘性 bias 精确可测，偏差报告配对校验，重校准产新版本，全参数 spec 与 `run_id`，Sleep 不重跑回测，冻结锚不被写回。实跑：后端 **444 tests OK**、前端 **38 tests passed**、`tsc -b` / `compileall` 干净、`frontend/src` CJK = 0。

### 12.5 边界与披露（不是缺口，是口径）

- 代理是「分组经验均值 + 校准残差 block bootstrap」，**不是**学到的市场动力学世界模型，不生成合成 bar（扩散 dream 仍后置）；未见分组回退到全局均值，误差由 `mean_absolute_error` 如实反映，不静默过滤。
- uncertainty 是 bootstrap 描述性离散度，区间是 bootstrap 均值的经验分位数；阶段 4 已补**多重检验校正**：默认 stepdown 提供族级 FWER 控制（block sign-flip + max-statistic，Romano-Wolf / Westfall-Young 口径，无需 iid 假设）；**没有**的是共形有限样本修正与覆盖率保证（CP 刻意不启用、不宣称），以及跨轮自适应序贯意义下的保证。
- `amplification` 在 `expected_bias = 0` 时为 `None`，不伪造分母；乘性注入的期望偏移按**注入前基准值** `base_reward` 计算，不按真实 reward，否则放大倍数会失真。
- 无多轮调度、无每轮 experiment run 留痕、无 ⑥ Statistical Feedback 回流（阶段 4）；`Interaction` / 前端仍无环境页（阶段 5）。（**阶段 4 收尾更新**：前三项已于阶段 4 由 `LoopOrchestrator` 补齐，此处保留阶段 3 交付时的边界快照。）

---

## 13. 阶段 4 设计与一手依据（2026-11-11）

### 13.1 一手核实

| 来源 | 核实内容 | 本系统用法 |
|---|---|---|
| statsmodels `statsmodels/stats/multitest.py`（GitHub `main`） | `multipletests(pvals, alpha=0.05, method="hs", maxiter=1, is_sorted=False, returnsorted=False)` 返回 `(reject, pvals_corrected, alphacSidak, alphacBonf)`；`fdr_bh` 委托 `fdrcorrection(method="indep")`，BH 校正为 `min_{j≥k} p_(j)·m/j` 并截断到 1；`bonferroni` 为 `p·ntests`、`alphacBonf = alpha/ntests` | 只用于 `IndependentBaselineMethod` 对照，测试逐值核对；默认方法不用 |
| MAPIE v0.9.1 `mapie/utils.py` | `compute_quantiles(vector, alpha)` 逐字为 `np_quantile(vector, ((n + 1) * (1 - _alpha)) / n, method="higher")`；`check_alpha_and_n_samples` 要求 `n ≥ 1/alpha` | 只用于可选 `SplitConformalCalibrator` 的分位数级别；默认方法不用 |
| Prefect `src/prefect/states.py`（GitHub `main`） | `StateType` / `Completed()` / `Running()` / `Failed()` / `Pending()` 工厂、`StateGroup` 聚合；状态名 PENDING / RUNNING / COMPLETED / FAILED | `StageStatus` 与 `StageRecord` 照此命名；不引入 Prefect（异步运行时 / 服务端依赖与纯函数阶段不匹配） |
| 本地 `arch 8.0.0` / `scipy 1.17.1` / `statsmodels` | `IIDBootstrap(..., seed=np.random.Generator).apply(np.mean, reps)` 返回 `(reps, 1)`；`scipy.stats.t.sf`、`statsmodels.stats.multitest.multipletests` 可导入 | 横截面批次量的描述性区间、对照方法的 t 近似与 FDR 校正 |

**未取到的一手（如实披露）**：MAPIE `mapie/utils.py` 的 `main` 分支 404（v0.9.1 可取，故引用 v0.9.1 并标版本）；阶段 3 记录的 `mapie/regression.py` 两个分支 404 仍成立。Prefect 源码只用于状态命名，未引入其实现。

### 13.2 方法选型（Anthony 2026-11-11 纠正）

> 原话：「注意，要采用合适的统计与不确定性方法和工具，别死磕CP，最重要的是要最合适！」

据此推翻了「阶段 4 把共形校准补上」的默认思路，按系统实际的两个被测量分别选方法：

1. **为什么 CP 不是默认**：split conformal 的有限样本覆盖保证依赖校准残差与待预测残差可交换；本回路每轮用同一冻结窗口、策略随反馈更新、代理每轮重校准，交换性不成立。硬套 CP 只能得到一个没有保证的分位数，还要背一个假口径。故 `SplitConformalCalibrator` 降级为可选对照，`exchangeability_valid_in_adaptive_loop=False`、`coverage_guarantee=False`；默认 `EmpiricalResidualCalibrator` 只报经验分位数与观测覆盖。
2. **为什么 BH-FDR 只是对照**：IC 序列相关、候选因子之间相关、多轮复用窗口，`multipletests` 依赖的独立/PRDS 假设不成立。`IndependentBaselineMethod` 保留它并在 spec 明写 `assumptions_valid_in_adaptive_loop=False`，作用是**把差距暴露出来**，不是给判据。
3. **主线方法**：逐 bar 因子值 → **block sign-flip 零分布**（整块翻符号，保留因子边际分布、自相关与跨因子依赖，只破坏与前向收益的对齐）+ **max-statistic stepdown**（每轮取全族 `max|IC|` 组成联合零分布，族级经验 p 值 `(1+#{null_max ≥ 观测})/(reps+1)`，Westfall–Young / Romano–Wolf 口径）；横截面批次量（批次 IC 均值、代理误差、代理不确定性）无时间顺序 → `arch.bootstrap.IIDBootstrap` 描述性区间。二者都是**描述性**，`guarantee_claimed=False`、`descriptive_only=True`。
4. **工具选型仍后置**：模块只固定 `UncertaintyMethod` / `CalibrationMethod` 可替换协议与一个合适默认实现，没有把任何统计工具定案；论文级统计口径按 §0.3 / §8 等模型与研究循环成形再定。

### 13.3 职责划分与唯一适配

- `ValidationFamily` 是只读投影：`FactorEvaluation.statistics` 的 IC 是唯一观测统计，**不重算**；冻结 bar records 只用于 block sign-flip 的零分布（前向收益），记录缺失就如实 `applied=False`。
- `StatisticalEngine._proxy_observation` 用 `training_engine.factor_reward` 得到真实 reward（reward 唯一入口不变），`SimulatedEstimation.reward` 为代理点估计，二者之差为校准残差。
- `StatisticalReport` 聚合选择结果、校准区间、稳健量、描述性 `reliability` 与 flags；`StatisticalFeedback.new_directions` 按「非入选 choice 的平均 |IC| 升序、平均代理不确定性降序」给出方向，不触碰任何冻结对象。
- `DirectionAdapter` 是 ⑥→① 的唯一写回点：只调用 `ExplorationPolicy.with_weights` 产新版本，且发生在**下一轮** ①，不绕过 `TrainingEngine.update`。
- 唯一适配：`pandas.DataFrame.corrwith` 用一次调用批量算零分布 IC（自动 pairwise dropna），`numpy.random.Generator` 生成块符号；没有手写相关系数递推，也没有引入 CP 专用库。

### 13.4 状态机与执行顺序

`STAGE_ORDER = (①, ②, ④, ③, ⑤, ⑥)`。原图编号是语义顺序，执行顺序按依赖：**Wake 裁决必须先冻结**（④ 的 `FactorEvaluation` 是 ③ 代理拟合的输入），⑥ 的 Statistical Feedback 按原图箭头回流到**下一轮** ①，不回头改本轮 ⑤。每段由 `infrastructure.execute_stage` 执行，纯函数阶段可确定性重跑，`StageRecord` 记录状态 / 输出指纹 / attempts / spec；机器运行时信息放 `LoopResult.environment` 且声明不进 fingerprint。

留痕：`ExperimentManagementFacade.create_run(configuration_snapshot=round_spec) → start_run → complete_run(metrics, artifacts)`；`run_id = fingerprint({loop配置, round, round_spec})[:32]`，同 seed 重放命中已 COMPLETED 的 run 即跳过，幂等。

### 13.5 验收证据

`tests/test_stage4_loop.py` 22 条：默认方法非 CP、族级 FWER 控制（宣称）/ 跨轮序贯不宣称、stepdown 同 seed 可复现、缺 records 不伪造、BH 对照逐值等于 statsmodels、IID bootstrap 区间逐值等于 arch 直接调用、经验与 CP 分位数公式、family 冻结契约、reliability / flags / directions、重试与停条件、六段顺序、同 seed 同指纹与 run_ids、每轮留痕与幂等、冻结数据与 Wake 指纹只读、⑥→① 反馈边生效（对照 NoOp）、可替换方法进 spec、JSON 安全、失败阶段保留记录、一条命令 CLI。实跑：后端 **466 tests OK**、前端 **38 tests passed**、`tsc -b` / `compileall` 干净、`frontend/src` CJK = 0。

### 13.6 边界与披露（不是缺口，是口径）

- `reliability` 是描述性复合量（跨轮 IC 符号一致性、代理一致性、观测覆盖、族级入选份额的均值），**不是**概率、跨轮序贯显著性或系统成功判据；它聚合了**FWER 控制的 stepdown 选择结果**，但跨轮自适应选择偏差本身仍由该描述性量承载，不包装为序贯覆盖保证。统计在回路中是「反馈 + 被测量」，**不是闸门**（不拦截候选、不改裁决）。
- 经验 p 值（默认 stepdown）**提供族级 FWER 控制**：block sign-flip 置换零分布 + max-statistic stepdown（Romano-Wolf / Westfall-Young 口径），无需 iid 假设，因此保证在序列相关与截面相关下依然成立；但多轮复用同一冻结窗口、策略自适应的**跨轮序贯意义下 `loop_level_sequential_guarantee=False`**。
- `IndependentBaselineMethod` 用 iid 正态 t 近似 + statsmodels `multipletests`（BH-FDR），FDR 控制在独立/正相关依赖下成立，但金融 IC 序列相关且跨轮复用同一冻结窗口，假设在自适应回路中不成立，故 FDR **不在此处宣称**，仅作对照；零方差 / 观测不足因子取 `p=1.0`（无证据），不伪造。
- CP 实现只做分位数公式对照，不宣称 exchangeability、有限样本覆盖或在线覆盖；默认不启用、不宣称覆盖率。
- 未做：论文级统计定案、GRPO 真训练、扩散 dream、Jev 去留（闭环状态页已在阶段 5 完成，见 §14）。
- `python -m dynaloop.orchestrator` 默认用**显式标注的合成 demo bars**（不是市场数据）；真实冻结数据由 `--records` JSON 快照或调用方经 `FactorResearch.fetch_records` 注入。

## 14. 阶段 5 设计与依据（2026-11-11）

### 14.1 设计意图
闭环系统（阶段 0–4）已具备「一条命令 + JSON spec」的完整运行能力，但结果不可见、不可交互。阶段 5 只补**闭环状态页 + Interaction API**，把六段 trace 与统计反馈呈现出来；不新增任何算法逻辑，六段执行完全复用阶段 4 的 `LoopOrchestrator`。

### 14.2 接口职责（照既有分层）
- `interaction/api.py`：新增 `POST /api/loop/runs`（body = `LoopRunPayload`，全参数冻结；`source_key` 选真实冻结窗口，缺省用显式标注的合成 demo bars）、`GET /api/loop/runs`（列表）、`GET /api/loop/runs/{fingerprint}`（详情）。路由只调 `LoopOrchestrator.run(rows, source_metadata=...)` 与 `LoopRunStore`，不重算因子、不跑回测、不碰统计。
- `interaction/loop_store.py`：`LoopRunStore`（`save` / `get` / `list_all`）把 `LoopResult.to_dict()` 落盘为 JSON，附加 `origin` / `round_count` / `final_reliability` / `run_ids` / `experiment_id`；指纹由 `LoopResult.fingerprint()` 派生，写入即不可变，不覆盖既有 entry。
- 前端 `pages/LoopPage.tsx`：表单（数据源 / 符号 / 窗口 / 种子 / 轮数 / bias / 重采样次数）→ 提交 → 渲染每轮六段 `StageRecord`、逐轮可靠性与代理偏差、`StatisticalFeedback.new_directions`；全英文、规范金融术语；导航加 `/loop` 入口。
- 留痕复用阶段 4 既有的 `ExperimentManagementFacade.create_run → start_run → complete_run`；`GET /api/experiments/{id}/runs` 已是既有接口，闭环页直接消费。

### 14.3 验收与边界
- 验收项见 §7.8；实跑见 §1.2 阶段 5 状态更新块。
- 边界：阶段 5 **不产生新算法或新统计口径**，只是既有多轮回路的可见化与留痕入口；六段顺序、冻结锚、指纹幂等性全部继承自阶段 4，前端 / 既有生产代码零改动。

