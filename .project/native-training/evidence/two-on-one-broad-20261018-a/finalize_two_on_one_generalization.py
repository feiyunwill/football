"""Archive the frozen broad-start assessment and verify its standalone replay."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

import quality
from validate import ROOT, sha, source_fingerprint
from validate_learning import SEEDS


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assessment', 'audit', 'delivery', 'quality', 'work', 'artifacts'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(); current = source_fingerprint()
    audit = read(args.audit / 'report.json'); delivery = read(args.delivery / 'report.json')
    assessment = read(args.assessment / 'report.json'); protocol = read(args.assessment / 'protocol.json')
    assert audit['passed'] and audit['generalization_passed'] and delivery['passed']
    assert audit['source_sha256'] == current['sha256'] and assessment['source_before'] == assessment['source_after'] == current
    assert audit['report_sha256'] == delivery['assessment_report_sha256'] == sha(args.assessment / 'report.json')
    assert delivery['assessment_audit_sha256'] == sha(args.audit / 'report.json')
    assert delivery['source_before'] == delivery['source_after'] == current
    assert delivery['replayed_primary_episodes'] == 1000 and delivery['linked_delivered_core']
    assert [r['seed'] for r in delivery['models']] == list(SEEDS)
    for command in delivery['commands']:
        assert command['exit_code'] == 0 and sha(args.delivery / (command['name'] + '.log')) == command['sha256']
    for model in delivery['models']:
        assert model['episodes'] == 200 and model['raw_rows_bytes_equal']
        name = f"{model['seed']}-trained_sample.log"
        assert (args.delivery / name).read_bytes() == (args.assessment / name).read_bytes()
    verified = quality.verify(args.quality)
    for path, digest in delivery['reused_receipts'].items(): assert sha(Path(path)) == digest
    package = Path(delivery['package']); manifest = read(package / 'broad-manifest.json')
    assert sha(package / 'broad-manifest.json') == delivery['manifest_sha256']
    assert all(sha(package / name) == digest for name, digest in manifest['files'].items())
    artifacts = args.artifacts.resolve(); artifacts.mkdir(parents=True, exist_ok=False)
    work = args.work.resolve(); work.mkdir(parents=True, exist_ok=False)
    archive = artifacts / 'football-two-on-one-broad-native.tar.gz'
    with tarfile.open(archive, 'w:gz') as stream:
        stream.add(package, arcname='football-two-on-one-broad')
    # Exercise the actual archive and generated shell script from another path.
    extracted = work / 'extracted'; extracted.mkdir()
    with tarfile.open(archive) as stream: stream.extractall(extracted, filter='data')
    relocated = extracted / 'football-two-on-one-broad'
    assert all(sha(relocated / name) == digest for name, digest in manifest['files'].items())
    clean = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'LD_LIBRARY_PATH') and not k.startswith('GFOOTBALL_')}
    print('persistent-archive-reproduction', flush=True)
    with (work / 'reproduce.log').open('w') as output:
        result = subprocess.run([str(relocated / 'reproduce-broad.sh'), str(work / 'replayed')],
            cwd=work, env=clean, stdout=output, stderr=subprocess.STDOUT, timeout=1800)
    if result.returncode: raise RuntimeError('Archive reproduction failed; retained ' + str(work / 'reproduce.log'))
    assert (work / 'reproduce.log').read_text().count(': OK') == 5
    for seed in SEEDS:
        assert (work / 'replayed' / f'{seed}-trained_sample.jsonl').read_bytes() == (args.assessment / f'{seed}-trained_sample.log').read_bytes()
    evidence = ROOT / '.project/native-training/evidence/two-on-one-broad-20261018-a'
    evidence.mkdir(exist_ok=False)
    files = []
    for label in ('assessment', 'audit', 'delivery'):
        original = getattr(args, label); target = evidence / label; shutil.copytree(original, target)
        for path in target.rglob('*'):
            if path.is_file():
                assert sha(path) == sha(original / path.relative_to(target))
                files.append(dict(path=str(path.relative_to(ROOT)), sha256=sha(path)))
    shutil.copyfile(work / 'reproduce.log', evidence / 'persistent-reproduce.log')
    shutil.copyfile(Path(__file__), evidence / Path(__file__).name)
    final = dict(passed=True, agreed_next_goal_complete=True, source_sha256=current['sha256'],
        completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(), quality=verified,
        generalization_passed=True, success_mean=audit['success_mean'], seeds=audit['seeds'], groups=audit['groups'],
        versus_initial=audit['versus_initial'], versus_random=audit['versus_random'],
        primary_episodes=1000, distinct_geometries=200, strategy_episodes=5000,
        delivered_replayed_episodes=1000, persistent_archive_replayed_episodes=1000,
        reused_receipts=delivery['reused_receipts'], reused_duration_seconds=delivery['reused_duration_seconds'],
        scope=protocol['scope'], resources='Previous exact-source30-minute training/77-installed-test/resume receipts reused; no new training/speed claim',
        auditor_sha256=sha(args.audit / 'audit_two_on_one_generalization.py'),
        finalizer_sha256=sha(Path(__file__)), archive_sha256=sha(archive), archive=str(archive), archived_receipts=files)
    (evidence / 'report.json').write_text(json.dumps(final, indent=2) + '\n')
    shutil.copyfile(evidence / 'report.json', artifacts / 'acceptance.json')
    (artifacts / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in sorted(artifacts.iterdir()) if p.is_file()))
    report_name = 'two-on-one-broad-report-20261018.md'; report_path = ROOT / '.project/optimization' / report_name
    groups = {'interpolation': '原范围插值', 'deeper_attack': '更靠后的进攻', 'wide_attack': '边路进攻', 'close_defender': '近距离防守', 'varied_support': '不同队友位置'}
    initial = sum(r['initial'] for r in audit['seeds']) / 5
    random = sum(r['random'] for r in audit['seeds']) / 5
    builtin = sum(r['builtin_ai'] for r in audit['seeds']) / 5
    argmax = sum(r['argmax'] for r in audit['seeds']) / 5
    lines = ['# 2v1 冻结模型扩大起点验收', '',
        '本轮泛化验证通过：[最终审计](../native-training/evidence/two-on-one-broad-20261018-a/report.json)。', '',
        f"源码 SHA256：`{current['sha256']}`。模型与引擎保持上一阶段版本，本轮新增泛化证据。", '',
        '200 个不同起点，五种几何类型各 40 个；五个冻结模型各评估 200 回合，共 1000 个主要回合。所有模型使用同一场景列，统计按种子和场景交叉配对采样；5000 个策略回合不视为 5000 个独立场景。', '',
        f"主采样策略平均进球率 **{audit['success_mean']:.1%}**，未训练 **{initial:.1%}**，随机 **{random:.1%}**，内置 AI **{builtin:.1%}**。所有种子均超过自己的两项基线，配合门槛均通过。", '',
        '| 训练种子 | 进球率 | 未训练 | 随机 | 完成传球回合率 | 传球后进球率 |',
        '|---|---:|---:|---:|---:|---:|']
    for r in audit['seeds']:
        lines.append(f"| {r['seed']} | {r['success']:.1%} | {r['initial']:.1%} | {r['random']:.1%} | {r['cooperation']:.1%} | {r['cooperative_success']:.1%} |")
    lines += ['', f"相对未训练的提升区间：`{audit['versus_initial']}`；相对随机：`{audit['versus_random']}`。预先冻结的均值 ≥75%、逐种子优于基线、配合及区间门槛全部通过。", '',
        '| 场景类型 | 主采样策略 | 未训练 | 随机 | 内置 AI |', '|---|---:|---:|---:|---:|']
    for key, label in groups.items():
        row = audit['groups'][key]
        lines.append(f"| {label} | {row['trained_sample']:.1%} | {row['initial_sample']:.1%} | {row['uniform_random']:.1%} | {row['builtin_ai']:.1%} |")
    lines += ['', f'贪心 argmax 对照为 **{argmax:.1%}**。上述通过结论仅针对 categorical sampling。内置 AI 为 {builtin:.1%}，后续仍有策略可靠性差距；分组均值仅作诊断，不单独宣称显著性。', '',
        '评估器先逐回合复现旧协议 250 个策略回合，再运行新场景；所有载入与评估状态不变检查通过。迁移包使用自身核心库、数据和字体逐字节重现 1000 个新主要回合；实际持久归档解压到另一目录后，生成的脚本再次重放 1000 回合并通过五个输出 SHA256。', '',
        f"生产源码和五个模型完全未变，因此核对哈希后复用原完整质量、77 项独立安装测试、{delivery['reused_duration_seconds']:.2f} 秒训练稳定性及续训收据。本轮没有重新训练、重复 30 分钟计时或新增加速比测量。", '',
        f'持久产物：`{artifacts}`。解压原生包后运行 `./reproduce-broad.sh NEW_OUTPUT_DIRECTORY`，程序会执行全部五个模型并自动核对输出 SHA256。', '',
        '200 个几何配置与此前七个有限分区不重合；排除已记录的历史确认引擎种子，不声称覆盖未记录的全部训练种子。传球仍为决策边界近似观测。范围为单学习球员与固定 AI 队友的有界 2v1，未推断任意起点、11v11、GPU 或其他平台。', '',
        '本轮结果若用于未来训练设计，数据即转为诊断/验证；未来确认须重新注册独立起点与种子。详见[执行协议](two-on-one-broad-plan-20261018.md)。', '']
    report_path.write_text('\n'.join(lines))
    for link in re.findall(r'\]\(([^)]+)\)', report_path.read_text()):
        assert (report_path.parent / link).resolve().is_file(), link
    state_path = ROOT / '.project/optimization/next-optimization-state.json'; state = read(state_path)
    state.update(status='two_on_one_broad_frozen_goal_complete', agreed_next_goal_complete=True,
        long_term_goal_complete=False, current_report=report_name, report=report_name,
        current_report_scope=protocol['scope'], current_source_sha256=current['sha256'],
        audit='../native-training/evidence/two-on-one-broad-20261018-a/report.json', local_artifacts=str(artifacts))
    state['stages']['O19'].update(status='frozen_models_generalization_and_delivery_verified', goal_complete=True,
        generalization_passed=True, success_mean=audit['success_mean'], report=report_name,
        primary_episodes=1000, distinct_geometries=200, delivered_replayed_episodes=1000,
        persistent_archive_replayed_episodes=1000, reused_duration_seconds=delivery['reused_duration_seconds'])
    state['audit_history'].append(state['audit']); state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + '\n')
    for path, target in [(ROOT / '.project/optimization/README.md', report_name),
                         (ROOT / '.project/native-training/ROADMAP.md', '../optimization/' + report_name)]:
        with path.open('a') as stream: stream.write(f'\n冻结五模型的 200 个新起点泛化与交付复现验证通过，见[报告]({target})；原质量、安装与时长收据按同源码复用。\n')
    print(json.dumps(dict(passed=True, report=str(report_path), artifacts=str(artifacts))))


if __name__ == '__main__':
    main()
