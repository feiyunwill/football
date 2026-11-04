# 自动执行工作状态

长期目标已登记为active，尚未完成，不要标记complete或pause。

- 持久Python：`/root/work_space/football-artifacts/runtime-20261020-a/venv/bin/python`。
- O22已完成，收据：`../native-training/evidence/o22-execution-20261020-a/report.json`；试运行未证明学习提高，初始81%、64更新49.5%，这不是最终模型。
- O23当前源码：`579f89198b74c06875635efed1b780dfe5627329c842fc58446245bc20ee0113`。80项Python集成、完整C++契约通过，收据：`../native-training/evidence/o23-quality-20261020-b/report.json`。
- 初次O23质量a因新增测试未换算FormationEntry的负y缩放而失败；已修正测试坐标空间，单独契约和完整质量b均通过。生产采样设计没有改动。
- 原生构建：`/root/work_space/football-artifacts/work-o23-quality-build-20261020-a`。
- 训练研究：`/root/work_space/football-artifacts/work-o23-study-20261020-a`。
- 运行中的exec session：`76299`，先用write_stdin轮询。若会话已关闭，读study/report.json及progress.json确认实际结果，不要重启或覆盖研究目录。
- 十次训练：legacy与broad80，各5种子42/123/2026/31415/271828；每模型2048次更新，每256次更新保存完整FPPO并以新进程继续。研究全部训练后才打开旧验证集；不评估中间检查点，不新增确认。
- 已核实第一个legacy-42-u256完成，65536转移，约72.03秒；随后u512运行中。这仅为此记录创建时的快照，后续进度以运行文件为准。
- 训练源码、执行器、独立审计器、起点重建工具、协议和原生二进制已冻结。研究运行时不要编辑frozen字段列出的任何文件，否则研究会判失败。
- 每模型上限1283秒，10次训练总12830秒；子进程观测RSS512MiB，研究输出2GiB。构建、训练、评估保持串行。

## 完成研究后的动作

1. 核对report技术通过与全部10模型/80段结果，读取validation_passed。
2. 用 `audit_o23_study.py --study STUDY --output NEW_AUDIT_DIRECTORY` 独立审计。审计会从FPPO读取最终episode场景，与重建日志对照，并重算整数门槛。
3. 只有验证均值>=92%、逐种子>=83%、每类>=82%、配合均>=20%、比legacy均值至少高2百分点均通过，才冻结候选并新登记200个确认几何及引擎种子。
4. 新确认排除所有已记录历史场景/种子以及starts-*.log重建的训练数据。geometry是FormationEntry存储坐标，含负y缩放；比较时必须统一坐标空间。日志也保存球位置和缩放常量。
5. 新确认执行八周路线93%/每种子85%/每类85%/配合20%与相对O20冻结模型交叉配对bootstrap下限>0的门槛。原O20 FPOL1模型可用于显式推理对照，不可用作训练检查点迁移。
6. 验证失败保留结果，不打开新确认、不换种子、不放宽门槛；依据失败证据登记下一次有界验证方案。
7. 主学习门槛通过后继续O24的60分钟稳定运行与独立强对抗探索，以及O25当前源码安装/恢复/1000回合归档复现。所有真实结果齐全才可完成长期goal。

## 后续自动执行补充

- 已确认前两个完整模型legacy-42、broad80-42完成；二者最终FPPO的真实episode起点均与重建日志逐项一致。legacy-42的权重文本载荷还与O20冻结模型完全一致，未计算验证成绩。
- 最近观察第三个模型broad80-123完成u512、正在u768。此项是历史快照，必须轮询session76299或读取实时文件后更新。
- 新增 `confirm_o23_learning.py`、`exclude_legacy_episode_seeds.cpp`、`audit_o23_confirmation.py`，仅完成代码准备与Python语法检查，尚未编译新排除工具、生成新案例或执行新确认。prepare明确要求独立训练审计与验证通过，之后才登记新200案例。
- 新确认候选均值必须>=930/1000、每种子>=170/200、每类>=170/200、每种子观测传球及配合进球均>=40/200；相对O20冻结模型的10000次交叉配对bootstrap下限必须>0。工具保留全部五种对照，共5000策略回合，不把它们视作5000个独立案例。
- 排除工具为五种固定训练种子保守生成各524289个episode RNG值（可能大于实际使用量）；确认还排除已记录案例与当前训练起点，所有几何比较采用同一FormationEntry存储坐标加球位置。
- 新增 `o24_continuous_training.cpp` 和 `run_o24_stability.py`，尚未编译或执行。它们以“独立确认及审计已通过”为入口门槛，拟在同一持久原生learner中训练3600秒，每分钟恢复分支核对；独立保存稳定性检查点，不修改部署候选。不能把未执行工具当作一小时稳定性证据。
- 当前训练仍需完成全部10模型及验证；不得编辑研究protocol.frozen列表中的文件。未来新工具不在该冻结列表，可在未打开新数据前修正，但实际执行前须记录自身哈希。

## 最新状态：首候选失败，第二候选续训中

以上训练进度均为历史快照。session76299已正常结束：十模型和2000验证回合完成，技术执行通过，但broad80验证85.9%低于legacy89.9%，没有打开确认。独立审计也确认均值、对照提升、逐种子和分组门槛失败；配合门槛通过。

- 失败报告：`o23-broad80-rejection-20261020.md`；完整原始研究和审计仍在外部持久目录，收据另存`evidence/o23-rejected-20261020-a`。
- 固定旧验证集推理消融已完成：broad80的balanced85.9%、sample89.5%、argmax70.5%；不能按种子拼选推理方式。消融外部目录`work-o23-inference-diagnosis-20261020-a`，技术执行通过，不代表学习通过。
- 第二候选协议：`o23-extended-budget-protocol-20261020.md`。唯一改变量为全部五个broad80模型从2048续训到8192更新；每模型24段、每段256更新，只有最终8192评估。legacy仍为2048，明确计算量不同。
- **当前活动exec session为7530**。先轮询，不重启。外部实时目录：`/root/work_space/football-artifacts/work-o23-extended-20261020-a`。初次观察为`train-broad80-42-u2304`。
- 不得编辑新研究`protocol.json`的frozen文件，包括`run_o23_extended.py`、`audit_o23_extended.py`、原审计器、两轮研究报告、诊断报告、8192协议、原始检查点和构建依赖。新工具只是准备；实际结果以report/progress为准。
- 追加训练每模型4200秒，总21000秒，观测RSS512MiB，输出2GiB；预期约2.4小时，资源与段间完整恢复继续记录。所有重任务串行。
- 新研究结束后先运行`audit_o23_extended.py --study STUDY --output NEW_AUDIT`，不用仅适用于2048的原研究审计器。验证失败仍不打开确认；不能无限追加第三个候选，先审计实现与任务定义。
- 如果验证及独立审计通过，现有`confirm_o23_learning.py`可接收新study/audit；它会读取五个最终候选的完整starts日志，排除新增的全部实际训练起点。注意新研究只列五个broad80模型；legacy对照通过已审计前序收据引用。
- 新增压力诊断`run_o24_pressure.py`、独立2v2探索`o24_two_on_two.cpp`与`run_o24_two_on_two.py`，仅语法检查及代码准备，尚未编译或运行。2v2 factory已改为零参数make后赋值；保留两名共同学习球员与固定AI队友2v1的任务差异。
- 93%确认、一小时持久训练及O25独立安装/恢复/1000回合归档复现仍未完成，长期goal继续active。

## 最新状态：两轮训练结束，首次新确认失败，转入实现审计

以上所有运行会话均已结束，**当前没有活动训练/评估会话**；不要重启session7530或35221。

- 第二候选五模型全部完成8192更新，追加训练8549.996秒。旧验证933/1000，通过原全部门槛；`audit_o23_extended.py`独立审计通过。外部目录`work-o23-extended-20261020-a`和`work-o23-extended-audit-20261020-a`。
- 首个全新确认完成：`work-o23-confirmation-20261020-a`，独立审计`work-o23-confirmation-audit-20261020-a`。候选927/1000、O20对照885/1000、采样926/1000、随机680/1000、内置AI970/1000。
- 确认未通过：均值不足930/1000；交叉配对bootstrap提升4.2个百分点，95%区间[-1.6,10.2]个百分点，下限未大于0。逐种子（194、195、170、174、194）、分组和配合门槛通过。不能据此修改验收、选种子、换统计或把差三个回合当作通过。
- 报告`o23-extended-confirmation-rejection-20261020.md`；收据和案例另存`evidence/o23-confirmation-rejected-20261020-a`，原始全日志仍保留在外部目录。
- 两个训练候选已用完。按8192协议，先审计训练/推理实现与任务定义，再依证据另立受限阶段；**不要直接追加第三轮训练**。当前确认集若用于改进设计即转为验证资料，未来确认须重新登记并排除此集及所有实际训练起点。
- 实现审计已开始（Verify级）：图项目`root-work_space-football`，覆盖元数据generation `2026-10-19T22:16:24Z`。已查`CooperativeReward`唯一直接生产调用`PpoLearner::train`，精确源码为`ppo_learner.cpp:161–208`，读了`PrepareAdvantages:39–66`及整个`ppo_math.cpp`，以及`cooperation_metrics.hpp`和`deterministic_inference.hpp`。
- 四个审计路径coverage为metadata_match/no_recorded_issue，仅代表无记录缺口。当前检查未发现可立即修复的明确算术错误；这不是完整无缺陷结论。GAE区分终止/截断、PPO裁剪梯度、熵符号、Adam和一次配合奖励均已初读，下一步追踪`NativePolicyEnvironment::step`与推理观测构造、动作sticky历史、reset和任务几何坐标，再用有界对照验证机制假设。
- 生产源码仍为`579f89198b74c06875635efed1b780dfe5627329c842fc58446245bc20ee0113`。主目标未达成；O24/O25仍不得冒记完成。长期goal保持active，当前不存在需要用户输入的阻塞。

## 最新进展：有界路径回放通过，末期波动确证，登记O23R

- 当前没有活动重任务会话；session18590（回放）和33547（末期诊断）均已正常结束。不要重复启动它们或原训练。
- 新工具`audit_o23_rollout_parity.cpp`和`run_o23_rollout_parity.py`已实际编译执行：五模型、每类固定四个旧验证案例，共100回合4784决策。训练适配器与官方sample推理的完整引擎摘要、观测、sticky、动作/RNG、logprob/value、原始奖励/终止和配合计数一致。外部`work-o23-rollout-parity-20261020-a/report.json`通过；这是有界证据，不是完整无缺陷结论。
- `diagnose_o23_late_updates.py`已实际对固定7424/7680/7936/8192四版本回顾性旧验证回放（8192复用），无优化器更新、不挑检查点。外部`work-o23-late-diagnosis-20261020-a/report.json`通过。五种子进球数分别为：42=[188,179,186,196]，123=[185,199,195,196]，2026=[194,179,190,174]，31415=[195,167,189,177]，271828=[159,191,181,190]。波动范围7–16个百分点。
- 已登记下一受限阶段`o23-within-seed-averaging-protocol-20261020.md`，尚未实现/执行平均候选。它仅将每个种子自身四个固定末期模型等权平均，**零新增优化器训练、无跨种子混合、不选择每种子最佳**。balanced推理不变。原确认主门槛保持；新验证入口更严格：总950/1000、逐种子180/200、逐类180/200、配合/联合各40/200，且比原8192总进球至少多10。
- 下一步实现平均导出与独立审计：保留全部原FPPO，派生FPOL明确标注平均清单来源，不冒充可独立续训FPPO。训练恢复针对真实最新FPPO；推理恢复针对派生FPOL，并交付成员/来源清单。必须先验证再生成新确认（固定新生成种子20261020028），排除已失败确认和全部历史/训练起点。不要修改已冻结历史工具以破坏原收据；新增独立工具或版本。
- 附带发现未运行的`run_o24_pressure.py`原deep/wide生成范围超出官方推理输入边界，已将deep改为[.25,.279]、wide绝对y改为[.35,.395]、combined的x改为[.38,.43]以同时容纳落后支援。尚未运行压力测试；这不是主学习失败原因或生产修复。
- 新诊断收据另存`evidence/o23-implementation-diagnosis-20261020-a`。生产代码、源指纹及质量80项仍未变化。长期goal继续active，主确认、一小时稳定性和交付复现尚未完成。

## 最新进展：O23R平均完成，第二次新确认仍未过统计门槛

- **当前无活动重任务会话**。session14448（平均验证）及72914（第二批新确认）均已结束，不要重启。
- 新增并执行`run_o23_averaging.py`及`audit_o23_averaging.py`。每种子自身7424/7680/7936/8192四版本参数等权平均，零训练、无跨种子混合。Python math.fsum/4导出，独立审计用Fraction精确有理数重算，五模型各8724参数全部一致。原始FPPO仍未改动。
- 派生FPOL的header provenance/checkpoint_sha槽指向`models/{seed}-provenance.json`的摘要；清单明确它是推理派生物，真实训练恢复须使用最新原始FPPO，不能声称平均权重有自己的优化器状态。研究报告model.path是底层最新真实训练状态，并有path_role说明，model.policy才是平均推理策略。
- 平均旧验证960/1000（194、195、189、194、188），更严格入口全部通过；独立审计通过。外部`work-o23-averaging-20261020-a`及`work-o23-averaging-audit-20261020-a`。
- 为避免破坏历史冻结工具，新增`confirm_o23_averaging.py`，复制原确认流程，仅改变候选配置/选择断言为broad80_swa4、新生成种子为20261020028及说明。原确认脚本保持不变。第二批新确认排除此前失败案例，禁止种子总计2,621,128。
- 第二批确认：外部`work-o23-averaging-confirmation-20261020-a`；独立审计`work-o23-averaging-confirmation-audit-20261020-a`通过。候选957/1000、O20对照895/1000、sample917/1000、随机680/1000、内置AI965/1000。五种子候选192、193、192、192、188；对应O20为177、163、177、182、196。
- 均值、逐种子、分组和配合通过；**配对提升6.2个百分点，95%区间[0.0,12.4]个百分点，下限等于0，严格>0门槛失败**。不得改成>=0、换统计、重试相同候选确认或按种子挑选。报告`o23-averaging-confirmation-rejection-20261020.md`，案例和收据另存`evidence/o23-averaging-confirmation-rejected-20261020-a`。未来若本集用于设计即转为验证资料，新确认必须排除两批失败确认。
- 下一步按协议返回推理/优化机制审计，不继续尝试平均窗口。可定向追踪BalancedInference跨决策累计credit在控球/配合阶段变化时是否滞后：sample训练路径已一致，但balanced有额外历史；必须先用固定旧验证案例的动作/概率/阶段轨迹作证据，再登记单一受控干预，不能把假说当作已发现bug。候选同种子提升为+15,+30,+15,+10,-8个进球，差异结构需如实保留。
- 生产源码仍未变化，80项质量收据适用相同源指纹；若将来改生产推理及状态格式，必须重新做质量/安装并保持FPPO原守卫。原FPOL仅用于推理，不能偷渡成新源码训练恢复。
- 主目标、一小时稳定性、压力/2v2探索及O25安装/恢复/1000主回合归档复现均未完成，goal保持active。当前无需要用户输入的真实阻塞。

## 最新进展：上下文轨迹与单一干预均完成，登记退火候选

- 当前无活动重任务会话。session75247（上下文轨迹）和48130（阶段干预）已结束；不要重启原训练或确认。
- `audit_o23_context_credit.cpp`/`run_o23_context_diagnosis.py`固定mean4五模型各20个旧验证案例，只执行原balanced，fresh reset仅影子选择。100回合5072决策、99次首次配合阶段切换中55次首个动作受历史credit影响，子集99/100进球，不能据此称旧设计有害。`audit_o23_context_trace.py`从DIC1与概率独立重建全部决策，哈希/计数通过。外部`work-o23-context-diagnosis-20261020-a`及`work-o23-context-audit-20261020-a`。
- 已登记并实际执行`o23-phase-reset-protocol-20261020.md`的唯一规则：首次观测完成传球后，下次决策前重置credit一次。实验CPP`o23_phase_reset.cpp`和runner`run_o23_phase_reset.py`未改生产代码或权重；原balanced1000回合逐行与已审计mean4日志一致。
- 干预959/1000，对照960/1000；只有种子2026的一个回合从成功变失败，其余种子进球数相同。原970门槛和改善门槛失败，不开新确认、不试其他reset频率。`audit_o23_phase_reset.py`独立重算通过。外部`work-o23-phase-reset-20261020-a`与`work-o23-phase-reset-audit-20261020-a`。
- 下一单一训练机制候选已登记`o23-annealed-training-protocol-20261020.md`，**尚未实现、构建或训练**。依据是实际末期7–16个百分点波动，以及已排查采样路径并否定阶段重置干预。参考CleanRL公开PPO线性学习率退火，第187–190行；只读取源码未执行/安装，快照`work-o23-annealing-reference-20261020-a/ppo.py`，SHA256 `d8dfbb7ac0b21e747b77d6e6673e566db4d6cdacc83bcebcd19cf87ad0e459ae`。
- 唯一新增任务建议`2v1_broad_annealed`/variation5/schema5，broad80几何/奖励/网络/PPO其余参数不变。有效LR=`0.0003*max(0.1,1-version/8192)`，version为更新前全局累计更新数，8192后下限保持；每次更新实际LR入日志。原任务保持固定LR与旧行为；恢复不能按256段重置schedule。
- **源码当前仍未改变**，仍为579f891...。改动前真实生产输入已完整归档`/root/work_space/football-artifacts/work-o23-pre-annealing-source-20261020-a/source.tar`及source-inputs/source-before收据（1335文件）。接下来可以按协议实现，但不得编辑历史冻结工具破坏收据：例如旧`dump_o23_training_starts.cpp`须另建新版本支持variation5，原始构建/证据目录不覆盖。
- 下一步先图查询/覆盖与直接源码核验相关采样、payload、训练/CLI及测试，新增有意义schedule边界、旧任务不变、跨任务拒绝和短恢复一致性检查。新构建目录与质量收据必需，旧FPPO因source守卫不得移入新源码；旧FPOL可显式推理对照并做1000旧验证逐行回归。
- 新任务短试运行固定42、64更新，完整64 vs32+32的FPPO/FPOL/轨迹相等及逐更新有效LR验证，上限1800秒。未通过不得启动五模型。完整预算已按实际8192成本登记：五种子各8192从支持初始化训练，每256完整恢复，只最终8192验证；预计11409.661秒（约3.2小时），每种子5113秒、总25565秒，RSS512MiB/输出2GiB，全部重任务串行。
- 新阶段验证入口970/1000、逐种子/逐类180/200、配合40/200；未来新确认生成种子20261020031，仍用原930/170/170/40/40及交叉配对CI严格>0，排除两批失败确认和所有新训练起点。不搜索其他LR周期/地板，不按失败种子追加训练。
- 新上下文/干预/参考收据另存`evidence/o23-context-phase-diagnosis-20261020-a`。主目标与O24/O25未完成，goal继续active；没有真实外部阻塞。

## 最新进展：退火实现与81项质量、短恢复试运行通过

- **当前没有活动重任务会话**。质量a session92785失败，质量b session17758通过，短试运行session32627通过，均已终止；不要重复轮询/启动。
- 生产代码已实现独立`PpoScenarioVariation::TwoOnOneBroadAnnealed=5`、`--scenario 2v1_broad_annealed`和FPPO内层schema5。IsCooperativeVariation包含5；ApplyPpoStart允许5并与4共享完全相同的broad80采样分支。基础奖励/视图/动作/PPO参数未改。
- `PpoEffectiveLearningRate(variation,version,base)`对原0–4任务原样返回base，对5返回base*max(.1,1-version/8192)。PpoLearner::train按更新前全局version计算，仅给本次UpdatePpo的参数副本设置有效LR，配置仍保存base。PpoIteration新增learning_rate，CLI逐更新输出。正式文档已更新。
- 新C++契约覆盖边界0/4096/7372/7373/8192/1e12、旧任务恒定、700个seed/partition采样等价、新5恢复及5/4双向拒绝。Python新CLI测试覆盖2 vs1+1完整状态和LR全局时钟、schema5及双向任务拒绝。
- 首次质量a新增恢复测试失败：writer已写schema5配合历史，但decoder两处仍只识别schema3/4。已改成IsCooperativeVariation(variation)，同时保证配合计数读取和native持球一致性检查适用于5。不是放松守卫。失败源码7534f29...归档`work-o23-annealed-rejected-source-20261020-a/source.tar`，失败报告`work-o23-annealed-quality-20261020-a/report.json`保留。
- **当前源指纹为`b4a83c75f533dc91becf06f5682794d4ea2f215eb63b6c9776f238aa9e6db98c`**，不再是579f...。原旧完整源码仍在`work-o23-pre-annealing-source-20261020-a`。
- 新构建目录`/root/work_space/football-artifacts/work-o23-annealed-build-20261020-a`，质量b`work-o23-annealed-quality-20261020-b`完整通过：81个Python集成测试（150.956秒，无跳过），全部原生契约/链接检查。旧质量对当前源已过期，不可复用；新质量b可通过quality.verify核验。
- 新工具`run_o23_annealed_pilot.py`、`dump_o23_annealed_starts.cpp`和`audit_o23_annealed_pilot.py`均已执行。dumper另建版本只接受variation5，最多2097153起点，历史冻结helper未改。
- 短试运行目录`work-o23-annealed-pilot-20261020-a`、独立审计`work-o23-annealed-pilot-audit-20261020-a`均通过：42/hidden64/epochs4/minibatch64/rollout256/cadence10/episode_limit256；完整64和32+32的FPPO/FPOL字节及每更新轨迹相等，64次有效LR/1024个真实优化器步数、最终起点重建通过。真实完整64耗时17.647803秒，投影8192约2258.919秒<5113秒登记上限。
- Pilot严格验证了schema5不能作为旧constant broad4恢复，且用完全匹配旧broad4配置尝试加载历史source579f的FPPO，被明确的`Incompatible training build or runtime dimensions`拒绝（exit1）。旧FPPO仍不能迁入新源码；旧FPOL只能作推理。
- 短试运行报告SHA256`687a7729cccb0248efde22abd07846cd30b1b1055ef82896579ecf43e2aa62a6`，协议SHA256`6ceabe4e5e947b6b7fea39d3f9d006a4e8417783bc392c525b35d6916598908b`。收据另存`evidence/o23-annealed-preflight-20261020-a`，包含质量a失败、b成功、pilot和audit。
- **完整五种子研究尚未实现/启动**，下一步需实现新的研究runner及独立审计器，不要修改历史冻结runner。入口核验新qualityb和pilot/audit；仅新原生支持初始化训练5任务（不能复用64pilot或旧FPPO作为最终训练初始化）。可复用pilot/starts二进制并冻结哈希。
- 新研究先以新源码官方CLI回放旧constant8192和mean4的便携FPOL两组各1000旧验证回合，与原日志逐行一致后才开长训练（协议承诺两组回归）。旧constant参考`work-o23-extended-20261020-a`（model.policy、validation-broad80-{seed}.log，933/1000），mean4参考`work-o23-averaging-20261020-a`（model.policy、validation-{seed}.log，960/1000）。案例均为原200，文件相同。旧源报告只能作已归档推理参考，不运行旧quality.verify冒充当前版本质量。
- 五模型固定42/123/2026/31415/271828，各8192更新（32段256），每段完整恢复，最终导出FPOL；没有中间验证/平均/挑种子。第一模型第一256段的前64更新可对照pilot/full64.log确保已支持初始化与配置一致。新helper按sum(completed_episodes)+1重建全起点；原`audit_o23_study.native_start(path,seed,5,8192)`纯FPPO parser可读取schema5，不必修改历史工具。
- 完整研究预算及门槛沿`o23-annealed-training-protocol-20261020.md`：每模型5113秒、总25565秒、观测RSS512MiB/输出2GiB、串行；只最终8192统一旧验证，970/1000、逐种子/逐类180/200、配合40/200。实际全部日志、有效LR、version、optimizer步数与恢复链需独立审计后，才新登记确认（生成种子20261020031，排除两批失败确认和所有历史/新训练起点）。主确认930/170/170/40/40与10000交叉配对CI下限严格>0保持不变。
- 当前无真实外部阻塞，goal继续active。81项质量与短恢复通过仅属基础设施，主目标和O24/O25均未完成。

## 最新状态：2000回放一致，五种子退火研究已启动

- **当前活动exec session为30983，必须先用write_stdin轮询，不能重启或覆盖目录。** 外部研究：`/root/work_space/football-artifacts/work-o23-annealed-study-20261020-a`。当前观察seed42完成1024更新（262144转换），u1280运行中，约128MiB/FD3，无错误。此为快照，以live handle及实时文件为准。
- 新增并实际启动`run_o23_annealed_study.py`，独立审计器`audit_o23_annealed_study.py`已写好并冻结，但最终审计尚未运行。所有生产源码、研究执行器/审计器、历史native_start解析器、新起点helper、预算协议、质量/pilot/audit收据、当前二进制/核心、两组旧FPOL及原始回放日志均在新protocol.frozen中，运行期间不能编辑。
- 入口已重新核验当前源b4a83c...质量b、81测试及pilot/audit。两组旧portable FPOL（constant8192、mean4）各5×200共2000回合在当前新源码官方balanced CLI回放，与原每回合JSON（步数/分数/奖励/配合/种子等）完全一致，另已独立逐行核验。不是重新训练旧模型，也没有尝试迁移旧FPPO。
- 当前开始五个全新原生初始化，不加载旧FPPO或64pilot作为初始化；种子42、123、2026、31415、271828，各32段256更新，最终8192。第一模型首256段的前64更新与pilot/full64.log逐项一致，研究known_pilot_prefix_matches=true；首段FPPO和当前1024段FPPO哈希及全局LR均已直接核验。
- full研究每段文件`train-annealed-{seed}-u{version}.log/.stderr`及`models/annealed-{seed}-u{version}.fppo`，最终`annealed-{seed}.fpol`。每个完整模型结束后用pilot/starts重建`starts-annealed-{seed}.log`，记录真实FormationEntry存储坐标/ball/scale。当前完整模型0/5，未打开验证。
- 资源与进度：resources.jsonl每2秒采样；progress.json仅保存最近已完成命令，可能比正在运行的命令落后一段，passed=false为进行中默认值，不能视为失败。缺少新stdout也不是停止；只以handle终止/最终report判定。
- 原预算未变：每模型全程5113秒（包括起点重建）、实际训练子进程合计25565秒、RSS512MiB、输出2GiB。每256更新FPPO完整跨进程恢复；原0–4固定LR保持，新5按全局version推进。只最终8192统一验证，970/1000、逐种子/逐类180/200、配合40/200，原legacy提升门槛保留。
- 终态技术执行通过后，运行`audit_o23_annealed_study.py --study STUDY --output NEW_AUDIT`。它核对2000portable回放、160训练段/每次实际LR/16个optimizer步数、完整哈希、5模型起点及整数门槛。验证失败保留，不开确认。验证和独立审计都通过后才新增确认工具（不要改历史冻结脚本）：选择annealed模型，生成种子20261020031，排除全部历史及两批失败确认和新训练完整起点；主930/170/170/40/40与10000交叉配对CI下限严格>0不变。
- O24持久训练旧工具配置仍为variation4，未来若新5通过主确认，应新建/版本化helper选择schema5，不能误加载；当前不要编译/运行额外重任务与训练竞争。压力/2v2/O25仍未实际执行。长期goal继续active，尚未达成，也无外部阻塞。

## 最新补充：训练继续，后续schema5工具只完成准备

- 活动session仍为**30983**，当前外部`work-o23-annealed-study-20261020-a`。最近直接核验seed42的u2304（589824转换）及FPPO哈希/全部逐更新LR，最新资源采样显示u2560运行中，约128MiB/FD3，无错误。完整模型仍0/5、尚未验证；应先轮询实际handle和文件，不重新启动研究。
- 新增`confirm_o23_annealed.py`，Python语法通过，**未运行prepare或run，未创建确认案例**。从历史原确认工具独立复制，选定配置annealed/生成种子20261020031；统计门槛与模式保持不变。额外追踪当前protocol的old_study、mean_study、predecessor、training_study链，对每个关联report/protocol核对登记哈希并记录完整starts日志，排除前序source579f训练几何，即使当前模型实际episode数更少也不遗漏。两批失败确认案例仍由evidence/cases.json检索排除。不能提前生成确认或把语法检查当作执行结果。
- 新增`o24_annealed_continuous_training.cpp`及`run_o24_annealed_stability.py`，仅代码准备（Python AST通过），**未编译或运行**。配置明确使用TwoOnOneBroadAnnealed/schema5，模型选择annealed42；要求确认report与当前study哈希绑定，确认FPOL与模型策略哈希相等。冻结全部五个原始FPPO/FPOL及确认复制FPOL。
- 一小时helper在每个真实train(256)及分钟恢复分支train(16)检查LR为base*.1，仍保持同一持久进程3600秒、50次以上恢复、资源窗口、无观察到构建竞争和worker回收门槛，候选文件不可变。未通过主确认前不能执行这些工具。
- 原历史工具保持不变，当前冻结研究的任何文件及生产源码均未编辑。新工具不在活动研究frozen列表，后续可在未打开数据前定向修复，但实际执行前须重新记录自身哈希。继续保持全部重任务串行，长期goal仍active。

## 最新训练快照：退火首模型8192完成，第二种子运行

- 活动session仍为**30983**，保持原研究，不重启。`work-o23-annealed-study-20261020-a`现完成1/5：seed42最终8192，模型训练/起点重建2367.808秒，41177个保守起点。seed123已启动（最近资源显示u512），约128MiB/FD3，尚未打开统一验证。
- 已独立直接核验seed42全部32段FPPO哈希、每段版本/转换、所有8192个实际LR值和131072个optimizer步数；7373附近下限跨越及最终floor均符合登记规则。最终FPPO/FPOL哈希和native_start(...,42,5,8192)与完整起点日志一致。
- 另做纯日志对照：seed42首次更新在新增learning_rate字段之外的全部原字段（包括trajectory_sha、reward、loss、gradient/parameter_delta等）与历史constant broad80首次更新精确相等；两者初始LR均0.0003。没有额外训练或评估。
- 新退火模型起点41177少于旧constant8192的42361，说明未来确认必须保留准备工具中前序study完整训练几何排除链，不能仅依赖当前study几何；当前仍未生成新确认案例。
- 本快照是已验证进度，不是学习效果验收。余下种子仍按123、2026、31415、271828顺序全新初始化各8192，全部完成后统一旧验证及独立审计。source b4a83c...、预算和统计/确认门槛不变，goal继续active。

## 最新快照：退火模型完成2/5

- 活动session仍为**30983**，当前外部`work-o23-annealed-study-20261020-a`。seed123已完成8192，训练/起点重建2322.317秒，39687个保守起点；seed2026已启动（最近u512运行中），约128MiB/FD3，无错误。不要重启研究。
- seed123全部32段、8192个LR、131072 optimizer步数、完整FPPO/FPOL哈希与最终native_start(...,123,5,8192)起点对照已独立直接核验。模型42/123都已完成，未打开任何中间或最终验证。
- 首次更新对照又核实了123、2026：在新增learning_rate字段之外，全部原字段与历史同种子constant broad80首次更新一致，根状态记录了旧/新原日志SHA；这是初始化/单变量检查，不是模型效果验收。
- 后续仍按2026、31415、271828完成固定8192，五模型全部结束才统一验证及`audit_o23_annealed_study.py`。所有冻结文件、当前源b4a83c...及预算/门槛保持，future确认和一小时工具仅准备、未执行。goal继续active。


### Live continuation: annealed model 3/5 verified

Session 30983 remains live; seed 2026 completed 8192 updates. Independently checked all 32 checkpoint hashes, 8192 learning rates, 131072 optimizer steps, FPPO/FPOL hashes, and final native geometry against 38415 reconstructed starts. Training plus reconstruction: 2281.570335 seconds. Seed 31415 is now running. No intermediate policy evaluation; full validation and new confirmation remain pending. Frozen protocol and production files were not changed.


### Live continuation: annealed model 4/5 verified

Session 30983 remains live. Seed 31415 completed all 8192 updates; 32 checkpoint hashes, every effective learning rate, 131072 optimizer steps, FPPO/FPOL hashes and reconstructed native start checked independently. 39211 conservative starts; 2291.660045 seconds. Initial update also matches all historical constant-rate fields. Seed 271828 is now running. Validation and new confirmation still pending.


### Annealed five-seed campaign terminal: validation rejected

Session 30983 exited 0. Technical study and independent full audit passed; validation failed: 955/1000 < preregistered 970/1000 and group counts [195,200,192,191,177] include 177 < 180. Seed counts [193,194,182,196,190]; cooperation and legacy improvement gates passed. Total training 11544.846856 seconds. All five models, 160 chunks, 2000 portable regression episodes, every effective LR, native starts and hashes audited. No new confirmation opened; O24/O25 acceptance remains pending. Next: bounded retrospective old-validation-only late-checkpoint diagnosis, without selecting checkpoints, changing gates, or more training.


### Fixed schema5 mean4 rejected after independent audit

New derived policy: 965/1000, +10 vs final8192; all per-seed/family/cooperation gates pass, total 970 gate fails. Exact-rational auditor verified all 43620 derived parameters and unchanged real FPPO states. No window search or confirmation. The final and mean4 candidates both remain rejected. Next diagnostic compares sampled inference (the training action rule) on these fixed policies against the already recorded balanced old-validation rows, without new training or confirmation data.


### Sampling mismatch hypothesis rejected; next single-variable training hypothesis

Both fixed candidates were replayed with training-style sampled inference: final8192 931/1000, mean4 929/1000, below balanced 955/965. Independent 2000-row paired audit passed. Training exposure across five continuous families is approximately balanced; family4 was not missing. Reweighting family4 is a testable next hypothesis,not a proven fix. Proposed new versioned task changes only exposure probabilities: legacy20%,family4 40%,others10% each. Next turn must freeze protocol,implement compatibility and frequency contracts,run current-source quality and <=30minute pilot,budget from actual costs before five-seed training. Do not reuse old FPPO across source identities,lower gates,try more mean windows or open confirmation for rejected candidates. No live subprocess remains. Goal active and incomplete.


### 2026-10-21 schema6 reweight implementation and quality run

Prior goal turn made concrete progress:completed and audited schema5 campaign,rejected final and fixed mean4,completed late-update and sampled-action diagnostics. No live prior process remained. Archived exact b4a83c75 source before editing. Added task6/schema6 with legacy20%,family4 40%,others10% each;all prior task streams,conditional geometry,rewards,network and annealing unchanged. Added sampler frequency/determinism/geometry and cross-task/cross-process continuation contracts. Current source 452970a1d260aa599adc8951398ed3e8b8d30127181243dd0c1138da859faa31. Full serial quality session91342 is live;Python task6 continuation passed;native contracts pending. Prepared separate pilot/helper/auditor and budget-gated full study tools. No task6 training started. Pilot cap1800 seconds and full budget formula are frozen in the new protocol;no confirmation or O24/O25 completion claimed.


### 2026-10-21 current task6 training live: session32598

Full current-source quality passed:82 Python tests,all required native contracts/linkage. Source452970a1d260aa599adc8951398ed3e8b8d30127181243dd0c1138da859faa31. Pilot full64=20.055065053s;64 vs32+32 FPPO/FPOL/iterations identical,every LR and1024 optimizer steps verified,native starts and schema5/old-source rejection passed independent audit. Frozen measured budget:4620 seconds/seed,23100 actual training child seconds total,RSS512MiB,output2GiB.

Full runner session32598 remains live. Its2000 historical portable inference rows matched exactly;seed42 first512 updates independently checked against two checkpoint hashes,schema6,8192 optimizer steps,every LR and pilot64 prefix. Latest observed stdout train-reweighted-42-u768;progress active_command is last completed command and can lag. No model has finished8192 yet;no performance evaluation or new confirmation. Do not restart the live job or edit any protocol.frozen file. Full study artifact: /root/work_space/football-artifacts/work-o23-reweighted-study-20261021-a. On terminal report run audit_o23_reweighted_study.py into a fresh directory. Only validation+audit pass permits confirm_o23_reweighted.py prepare/run;adapter uses fresh generation seed20261021031,not yet generated. History collection follows all predecessors;both prior failed confirmation200-case sets were confirmed present in repository history. Existing strict primary gates and all O24/O25 requirements remain pending.


### Live continuation: task6 seed42 past midpoint; downstream proof tools prepared

Session32598 verified live;latest stdout train-reweighted-42-u5120. Zero full8192 models completed. Independently audited seed42 first4096 updates:16 checkpoint hashes/schema6,1048576 transitions,65536 optimizer steps,all effective learning rates and finite metrics. All41 frozen inputs and production source remain unchanged. Current training roughly128MiB RSS/3FD in recent sample. Do not restart the live job or edit frozen files.

Prepared but NOT compiled/run: o24_reweighted_continuous_training.cpp and run_o24_reweighted_stability.py. They gate on actual accepted confirmation/audit,bind the derived FPOL to original FPPO,freeze all mean4 members,restore from actual saved disk checkpoints,and preserve3600-second/quiet-build/resource requirements.

Prepared but NOT executed: verify_o25_reweighted_replay.py. It requires current-source independent installation,accepted confirmation+audit and real stability acceptance;copies the real source archive/wheel and native bundle;verifies1000 primary episodes in each relocated/archive location,all-five FIFS continuations,fresh schema6 full64 vs32+32,and copied compatible original-FPPO continuation across archive locations. Engine Run source was inspected:resumed summary episodes count only newly emitted rows,so prefix+tail episode/decision equality is checked. Loader-path normalization was checked against actual GNU bin/../ output. Only AST/import/helper checks were run for this preparation;no delivery claim. Generic pressure and2v2 tools were inspected and remain unexecuted,gated on accepted main confirmation.


### Live continuation: task6 model1/5 complete and independently checked

Session32598 remains live;seed42 completed all8192 updates and seed123 is running(latest observed stdout train-reweighted-123-u768). First model audit receipt: /root/work_space/football-artifacts/work-o23-reweighted-incremental-audit-20261021-a/seed42.json. Verified all32 checkpoint hashes,8192 LRs,131072 optimizer steps,40490 conservative starts and final native geometry,plus8724 exact-rational mean4 parameters and member/provenance hashes. Training plus reconstruction/mean took2793.310852 seconds<4620 cap. Reconstructed start probabilities:legacy8060,families[4136,4006,4134,3981,16173],family4=39.9432%;this is sampling evidence,not performance. Raw final FPPO ce52ca9fc6bd3061d0454df8be2403079713d6fec2ebc9659b0d24c174a3db32;primary FPOL b082ce80369381f1b798480e13b976951a9cb3e96572f3dc2231b067a256d6bb.

Prepared independent audit_o24_reweighted_stability.py,not run on any stability assessment. Its schema6 decoder was checked against actual pilot64 and training4096 FPPO,including full optimizer counters and envelope checksum. Audit reconstructs one-hour windows,raw progress/transition and optimizer arithmetic,disk checkpoint counters/manifests,quiet-run/worker/resource gates. Source UpdatePpo was read to verify16-transition restore branches make4 optimizer steps vs16 for256 transitions. Wrapper now freezes this auditor before future measurement.

O25 replay tool now requires a real --stability-audit receipt and binds upstream frozen study/confirmation/stability tools. It remains unexecuted. No compile or simulation was run alongside the main training,except the already registered serial study itself. Production source and all41 study-frozen inputs were rechecked unchanged. All primary validation/confirmation gates and O24/O25 actual acceptance remain pending. Next:poll32598;do not restart or edit frozen files.


### Live continuation: seed123 quarter audit and future-interface verification

Session32598 remains live;latest observed stdout train-reweighted-123-u3072. One full model finished;seed123 first2048 updates independently checked:8 checkpoint hashes,state isolation,all LRs,32768 optimizer steps in raw logs,524288 serialized transitions,and native episode metadata. Receipt: /root/work_space/football-artifacts/work-o23-reweighted-incremental-audit-20261021-a/seed123-u2048.json. Recent child sample about128MiB/3FD. All41 frozen inputs and source rechecked unchanged. This was progress plus verified live waiting,not a blocker.

Read actual confirmation runner and independent auditor:logs are {seed}-candidate.log(not candidate-{seed}.log);prepared O25 replay references corrected. Crossed bootstrap source was inspected:10000 independent row/column draws preserving paired model/case differences,RNG20261015,strict low>0 unchanged. Prepared task6 confirmation now freezes the generic independent auditor and its physical-geometry helper,and captures actual source_before at run start to satisfy delivery provenance. No cases generated or confirmation executed.

Compared exact current-quality and installed-integration module lists;prepared O25 tool will require matching actual test counts and executed schema5/schema6 test methods. It also preserves raw quality/install/stability evidence hashes alongside upstream frozen tools. These remain preparation only;no install,replay,stability or other heavy job ran alongside training. Next action remains poll32598 without restart or frozen-file edits;finish all5 before old validation,then independent full study audit and only if eligible fresh confirmation. Full original O22--O25 objective remains incomplete.


### Live continuation: task6 model2/5 completed and fully checked

Session32598 remains live. Seed123 completed8192 updates;seed2026 started(latest observed stdout train-reweighted-2026-u256). Full model receipt: /root/work_space/football-artifacts/work-o23-reweighted-incremental-audit-20261021-a/seed123.json. Independent checks:32 hashes,all8192 effective LRs,131072 optimizer steps in logs AND final serialized FPPO,40414 reconstructed conservative starts,final native geometry,all4 member/provenance hashes and8724 exact-rational averaged parameters. Training/reconstruction/mean:2682.391208 seconds<4620. Raw FPPO2cc9849d9ed5b1f9c0f74769b5da6596f18f7c4ce3cee2618b5b165dcc83ab4a;primary FPOLcb5ecefe4a5e1ee07e29efe0e275a618679324b9de596476fea838fdcd0139c7. Sampling counts:legacy8047,families[4141,4134,4038,4027,16027].

This goal turn made training/integrity progress plus verified waits;no blocker. Source and all41 frozen inputs rechecked unchanged. Recent2502 resource samples had observed peak127.83MiB,max4FD,output33.11MiB(at then-current partial model2). No extra build,training or performance evaluation was started. No intermediate policy performance assessed;all5 must finish before validation. Independent confirmation,one-hour stability,2v2/pressure and current-source O25 install/archive acceptance remain pending. Next:poll32598,do not restart/edit frozen files.


### Live continuation: seed2026 quarter audit and frozen-source backup

Session32598 remains live;latest observed stdout train-reweighted-2026-u2304. Two full models complete;third seed2026 first2048 updates checked independently:8 hashes,state isolation,all effective LRs,32768 logged optimizer steps,524288 serialized transitions,native episode metadata. Receipt: /root/work_space/football-artifacts/work-o23-reweighted-incremental-audit-20261021-a/seed2026-u2048.json. No performance evaluation.

Created /root/work_space/football-artifacts/work-o23-reweighted-source-20261021-a:exact current build-input backup,1335 archived files individually SHA256 verified and active source manifest matched before/after. ArchiveSHAe3e59df5c868af4f691388a3fc4ddcfa10739696d6de81a533f1a2748704993e. Receipt also binds active study protocol,native binary and core hashes. Snapshot tool was inspected:read-only Git file enumeration and tar creation;no builds or simulation. This is a source backup,NOT O25 installation or1000-episode archive replay acceptance.

Source and all41 frozen inputs remain unchanged. This turn made checkpoint/backup progress and verified waits;no blocker. Next remains poll32598 without restart or frozen-file edits. Finish all5,then full independent study audit,then only on eligibility fresh confirmation;all O24/O25 actual gates remain pending.
