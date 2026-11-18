# 实验平台审查与修复记录

日期：2026-11-11。范围：已有阶段 0–5 平台；不开发可训练大脑、扩散模型或新的研究算法。

## 审查结论

现有模块划分可以继续支撑实验，不需要推倒重写。本轮检查了 12 个模块的主要入口、关键数据与状态流、持久化和前端接入，修复了会影响数值正确性、可复现性、并发保存及数据泛化的缺陷。原有 472 项后端测试全部通过，但未覆盖以下多订单、状态传递、统计方法与快照边界问题；测试通过不能单独作为科学有效性的证据。

这是一次静态审查与回归验证，不是对所有输入、所有外部数据源或统计理论的形式化保证。

## 已修复的问题

| 范围 | 问题 | 修复与验证 |
|---|---|---|
| 撮合 / 账户 | 同批订单共用旧账户余额，可重复使用现金和持仓；EXIT_FIRST 卖出不能及时释放资金 | 逐笔成交即更新账户，避免引擎二次入账；增加重复买卖和先卖后买测试 |
| 订单顺序 / 费用 | FIFO 按字符串 order_id 排序，o-10 排在 o-2 前；部分成交将最低佣金与比例佣金同时扣除 | 保持同 bar 提交顺序；可买数量同时满足两种费用约束 |
| 回测报告 | 首 bar 成本未计入最大回撤；基准复制了不完整的费用公式；无交易结果可能在不同数据上共享指纹 | 回撤从初始资金起算；基准复用 Exchange / Account；指纹包含数据、spec、指标与基准，schema 升至 2 |
| 冻结输入 | 重复 symbol/timestamp 被覆盖；Frame.bars 和 FactorFrame.data 可被外部修改 | 重复数据显式报错；frame 映射只读、DataFrame 返回副本 |
| 因子输入 | 有一个缺失值就丢弃整列；NumPy 整数特征不能识别 | 保留可用数值列及真实缺失值，接受 Real 数值；缺失值在指纹中编码为 null |
| 因子生成 | 保存 / 恢复进程全局 random 状态在并发时并不隔离 | 每次生成使用独立 random.Random；并发与全局状态回归测试 |
| 多轮闭环 | 每轮重新 fit 代理，上一轮校准被丢弃；自定义 reward 未传递给代理和统计 | 显式传递前轮校准，版本连续递增；三处共享同一 RewardSpec |
| CLI / API | CLI 固定演示窗口；默认环境只接受日期，阻塞日内运行；非法参数可能返回 500 | CLI 从快照解析边界及列并支持显式覆盖；运行窗口不再混用环境的半开区间；配置统一校验，API 返回 422；近期源沿用实际返回窗口 |
| 统计计算 | 各因子独立抽符号，违背共享重采样说明；实际上只做单步 max 校正；忽略时间戳及 IC horizon | 共享符号、按剩余假设逐步取 max 并单调化 p 值；按时间戳对齐且核对数据指纹；使用真实 horizon |
| 统计声明 | 未验证假设即声称 FWER；跨因子 IID 区间被写成有保证的区间；报告对不同方法一律标 FWER 成立 | 撤回无依据保证；输出经验诊断及描述性区间；报告由所选方法的元数据决定 |
| 统计对照 | Pearson IC 恰好 ±1 被当作不可用并赋 p=1 | 有效样本下使用 iid 对照的极限 p=0，仍不声称适用于自适应闭环 |
| 指纹 / 存储 | family identity 漏掉 choices；五套 JSON 存储重复且固定 .tmp 名，并发易覆盖 | identity 纳入 choices / reward；共享 JsonMappingStore，文件锁覆盖读改写事务，唯一临时文件 + fsync + 原子替换 |
| 初始化 | 导入 API 模块即打开用户默认数据库 | create_app 无导入副作用；保留 api:app 的惰性兼容入口，推荐 uvicorn --factory |
| 冗余 / 前端 | 回测与研究重复序列化和版本逻辑；所有页面首次打入单包 | 公共逻辑移到 Infrastructure，Research 旧入口兼容导出；前端路由按页面加载 |

实现入口：`validation_backtesting_engine/services/{engine,exchange,report}.py`、`research_engine/{frame,evaluation,spec}.py`、`model/grammar.py`、`orchestrator/`、`market_environment/runtime.py`、`statistical_uncertainty_engine/`、`infrastructure/{json_store,serialization}.py`、`interaction/api.py`、`frontend/src/app/router.tsx`。

## 覆盖的模块与保留的设计

- Data：检查源注册 / 能力缓存 / 取数窗口、内容寻址文件存储、发布与 SQLite 元数据；保留原有 adapter / facade 和不可变内容机制。修改限于公共 JSON 缓存与源配置存储复用。
- Validation & Backtesting：检查 feed、strategy 生命周期、exchange、account、report 和结果存储；修复账务及结果身份，不改变模拟交易定位。
- Research / Model / Inference / Training：检查 DSL 白名单与因果算子、评估标签、源特征、采样种子、候选去重和 reward / advantage；保留现有候选生成与策略更新算法。
- Market Environment / Statistical / Orchestrator：检查真实裁决、代理校准、跨轮反馈、统计输入与假设披露、配置和阶段记录；修复实现，不引入下一阶段训练。
- Experiment Management / Infrastructure：检查运行状态转换、配置快照、SQLite 事务、重试与公共序列化；保留现有实验生命周期。
- Interaction / frontend：检查参数边界、源接入、loop trace、回测视图与持久化；前端只调整路由加载，不重做 UI。

## AGENTS.md 清理

29,610 bytes → 2,734 bytes，减少约 90.8%。移除固定分工话术、重复强制词、历史练习制度与修订流水账；保留方向、授权范围、模块边界、Python 环境及真实验证要求。数据与 UI 的具体行为压缩到 `docs/data_ui_contract.md`（2,455 bytes），仅相关任务加载。核心设计只在架构 / 算法 / 评估任务读取。

`CORE_DESIGN.md` 的研究目标保留，但撤回“现有实现已保证任意依赖结构下 FWER”的错误表述；`system_contract.md` 标明历史快照与本次纠正，避免旧验收说明覆盖当前事实。

## 验证

- 修复前基线：后端 472 tests OK。
- 新增回归覆盖：多订单资金 / 持仓、FIFO、费用、首 bar 回撤、数据指纹、共享符号与真正 stepdown、时间戳 / horizon、代理跨轮状态、custom reward、CLI 外部窗口、API 非法参数、并发 JSON 保存、导入无副作用等。
- 前端：38 tests passed；`tsc -b && vite build` 通过，入口 JS 809.91 kB → 279.08 kB（未压缩）；最大按需 chunk 396.41 kB，无 500 kB 警告。这是拆包，不代表总依赖体积同比缩小。
- 后端最终全量测试：499 tests OK（31.571 秒，比基线新增 27 项）；`python -m compileall -q src tests` 通过。
- 前端源码 CJK 检查无匹配；Git 已跟踪差异空白检查通过。多数源码在本次开始时尚未跟踪，不能仅凭 git diff 评价其变更范围。

## 实验使用边界

1. 当前统计结果是经验诊断，不能直接作为论文中的有限样本 / FWER / 跨轮自适应保证。区块符号翻转的对称性与交集检验有效性仍需独立论证；单轮经验 p 值也不解决反复使用同一窗口的选择偏差。
2. 当前 Sleep 的初始拟合和部分残差评估使用同族数据，区间与 coverage 是描述性结果；跨轮重复同一历史窗口不增加独立验证样本。真实样本外实验应由调用方准备明确分离的快照。
3. JSON 存储面向本地文件系统，锁保证使用该实现的进程之间互斥；不承诺网络文件系统语义，也不提供大规模实验数据库的查询性能。新增依赖为 `filelock>=3.16,<4`。
4. 外部数据源在本轮未做在线全面验证，单元测试不能证明供应商服务可用或字段推断对任意新格式成立。Data 当前支持的布局之外应明确失败。
5. 核心回测支持任意标的集合，现有因子研究 facade 仍以单标的时间序列为契约；没有扩展成横截面组合研究系统。时间表示应一致且可排序，不自动猜测时区 / 日历。
6. 本次更正改变部分数值及指纹。保留旧实验记录；重新运行得到新身份，不应把新旧结果当作同一算法版本直接混合比较。
7. 未进行浏览器视觉验收、生产负载测试或新研究模型实验；源码审查与当前回归通过不等于不存在其他缺陷。

## 一手依据

- Python 独立随机数实例：https://docs.python.org/3/library/random.html
- Python 模块属性惰性访问：https://docs.python.org/3/reference/datamodel.html#customizing-module-attribute-access
- filelock 跨进程互斥：https://py-filelock.readthedocs.io/en/latest/
- Romano–Wolf，Exact and Approximate Stepdown Methods for Multiple Hypothesis Testing：https://www.econ.uzh.ch/dam/jcr:ffffffff-935a-b0d6-ffff-ffffd823d949/jasa.pdf

修复同时复用仓库原有 Exchange / Account、Data、研究评估与实验生命周期公开接口；没有建立平行回测或新的研究框架。

