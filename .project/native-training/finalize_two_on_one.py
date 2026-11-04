"""Preserve accepted 2v1 artifacts and receipts, then close the bounded goal."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

ROOT=Path(__file__).resolve().parents[2]
def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('audit','quality','study','learning','baseline','delivery','models'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();audit=read(args.audit/'report.json')
    assert audit['passed'] and audit['agreed_next_goal_complete']
    assert audit['resumed_models']==5 and audit['replayed_model_episodes']==1000
    delivery=read(args.delivery/'report.json');task=audit['tasks']['2v1']
    assert task['learning_passed'] and all(r['cooperation']>=.1 and r['cooperative_success']>=.1 for r in task['seeds'])
    artifacts=ROOT.parent/'football-artifacts/two-on-one-20261018-a'
    artifacts.mkdir(parents=True,exist_ok=False)
    package=Path(audit['package'])
    with tarfile.open(artifacts/'football-two-on-one-native.tar.gz','w:gz') as archive:
        archive.add(package,arcname='football-two-on-one')
    wheel_command=next(c['argv'] for c in delivery['commands'] if c['name']=='install-wheel')
    wheels=[Path(a) for a in wheel_command if str(a).endswith('.whl')]
    assert len(wheels)==1 and sha(wheels[0])==delivery['wheel']['sha256']
    shutil.copyfile(wheels[0],artifacts/wheels[0].name)
    export=next(c['argv'] for c in delivery['commands'] if c['name']=='export-source')
    source=Path(export[-2]);assert sha(source)==delivery['source_archive_sha256']
    shutil.copyfile(source,artifacts/source.name)
    shutil.copyfile(args.audit/'report.json',artifacts/'acceptance.json')
    artifact_hashes={p.name:sha(p) for p in artifacts.iterdir() if p.is_file()}
    (artifacts/'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name,digest in sorted(artifact_hashes.items())))
    receipts=[];evidence=ROOT/'.project/native-training/evidence'
    for label in ('audit','quality','study','learning','baseline','delivery','models'):
        source=getattr(args,label);source=source.parent if source.is_file() else source
        target=evidence/f'two-on-one-{label}-20261018-final';target.mkdir(exist_ok=False)
        for old in sorted(source.rglob('*')):
            if old.is_file() and 'work' not in old.relative_to(source).parts:
                new=target/old.relative_to(source);new.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(old,new);assert sha(old)==sha(new)
                receipts.append(dict(original=str(old.resolve()),archived=str(new.relative_to(ROOT)),sha256=sha(new)))
    manifest=evidence/'two-on-one-archive-20261018-final.json'
    manifest.write_text(json.dumps(dict(files=receipts,artifacts=dict(path=str(artifacts),files=artifact_hashes)),indent=2)+'\n')
    report_name='two-on-one-report-20261018.md';optimization=ROOT/'.project/optimization'
    lines=['# 2v1 配合进攻验收（2026-10-18）','',
           '本阶段目标已完成：[最终审计](../native-training/evidence/two-on-one-audit-20261018-final/report.json)。',
           f"源码 SHA256：`{audit['source_sha256']}`。",'',
           '一个固定学习球员与引擎 AI 队友，对抗引擎 AI 后卫及门将。主策略为 categorical sampling；五个独立训练种子，各 200 个新起点确认回合。',
           '每个模型从头训练 2048 次更新、每次 256 个转移，共 524,288 步。训练与评估均为完整任务，真实奖励始终保留；首次观测到前场传球加 2，之后实际正向进球再加 2 倍 score_reward，检查点不触发新增进球奖励。历史标志由实际持球观测生成。评估报告原始进球与传球指标；传球统计为决策边界观测，不能保证捕获 cadence 内所有触球。','',
           '| 种子 | 进球率 | 未训练采样 | 随机 | 完成前场传球的回合率 | 传球后进球率 |','|---|---:|---:|---:|---:|---:|']
    for row in task['seeds']:
        lines.append(f"| {row['seed']} | {row['success']:.1%} | {row['initial']:.1%} | {row['random']:.1%} | {row['cooperation']:.1%} | {row['cooperative_success']:.1%} |")
    lines+=['',f"平均进球率 **{task['success_mean']:.1%}**；相对未训练与随机策略的配对提升区间分别为 `{task['versus_initial']}`、`{task['versus_random']}`。预注册的均值、逐种子、配合与区间门槛全部通过。",'',
            f"当前源码持续运行 {audit['duration']['seconds']:.2f} 秒，{audit['duration']['transitions']} 个转移，{audit['duration']['tps']:.2f} 转移/秒。低外部负载门槛、资源回收与跨进程续训通过；仅代表观测到低外部负载的 WSL 运行，不代表物理主机隔离或新的加速比。",'',
            '实际独立 wheel 安装、原生目录迁移、完整训练/续训检查通过；交付程序逐批重现五个模型的 1000 个确认回合，五个模型续训结果与参考构建逐字节一致。',
            f'本机持久产物：`{artifacts}`，包括 wheel、精确源码、带模型原生包、验收记录及 SHA256SUMS。解压原生包后运行 `./reproduce-generalization.sh` 可重放评估。','',
            '早期验证试训及三轮独立确认失败均保留：g 的种子 42 未超过未训练策略；i 的种子 2026 未出现完成传球；k 的种子 2026 虽有配合，但进球率未超过两项基线。每轮均停止整轮、不替换种子；后续修订重新注册独立确认分区和种子。详见 [执行计划及修订](two-on-one-plan-20261018.md)。',
            '持续运行首次预检因后台索引负载超限被拒绝，未开始正式计时；低负载后以新目录重跑通过，门槛未变。[失败预检记录](../native-training/evidence/two-on-one-duration-preflight-rejected-20261018-l/report.json)保留。上述统计区间描述最终冻结的一轮有界确认，不作多轮调参后的总体显著性保证。',
            '范围仅为有界的固定学习球员 2v1 任务；不推断联合多球员学习、任意起点、完整 11v11、GPU 或其他平台能力。未推送或发布。','']
    (optimization/report_name).write_text('\n'.join(lines))
    state_path=optimization/'next-optimization-state.json';state=read(state_path)
    receipt='../native-training/evidence/two-on-one-audit-20261018-final/report.json'
    state.update(status='two_on_one_goal_complete',agreed_next_goal_complete=True,long_term_goal_complete=False,
                 report=report_name,current_report=report_name,audit=receipt,current_report_scope=audit['scope'],
                 current_source_sha256=audit['source_sha256'],local_artifacts=str(artifacts),
                 current_quality='../native-training/evidence/two-on-one-quality-20261018-final/report.json')
    state['audit_history'].append(receipt)
    state['stages']['O18'].update(status='learning_duration_delivery_verified',learning_passed=True,delivery_passed=True,
        audit=receipt,success_mean=task['success_mean'],quality=state['current_quality'],replayed_episodes=1000,resumed_models=5)
    state_path.write_text(json.dumps(state,indent=2,ensure_ascii=False)+'\n')
    for path,link in [(optimization/'README.md',report_name),(optimization/'two-on-one-plan-20261018.md',report_name),
                      (ROOT/'.project/native-training/ROADMAP.md','../optimization/'+report_name)]:
        with path.open('a') as stream:stream.write(f'\n2v1 配合进攻目标已通过学习、持续运行与交付复现验收，见 [最终报告]({link})。\n')
    print(json.dumps(dict(passed=True,report=str(optimization/report_name),artifacts=str(artifacts))))

if __name__=='__main__':main()
