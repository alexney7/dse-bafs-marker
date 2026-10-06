"""Validate a marking ledger and render an offline student HTML report (stdlib only)."""
import argparse
import html
import json
import math
from pathlib import Path


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Marks and weights must be finite numbers')
    return value


def analyse(data):
    sections = {s['id']: s for s in data['sections']}
    if len(sections) != len(data['sections']) or not sections:
        raise ValueError('Section IDs must be unique and nonempty')
    if data['scope'] not in ('full', 'paper', 'partial'):
        raise ValueError('scope must be full, paper or partial')
    weighted = all('weight' in s for s in sections.values())
    for s in sections.values():
        if number(s['max']) <= 0:
            raise ValueError('Section max must be positive')
        if 'weight' in s and number(s['weight']) <= 0:
            raise ValueError('Section weight must be positive')
    if any('weight' in s for s in sections.values()) and not weighted:
        raise ValueError('Supply all section weights or none')
    if weighted and (data['scope'] != 'full' or not data.get('weight_source') or
                     not math.isclose(sum(s['weight'] for s in sections.values()), 100)):
        raise ValueError('Whole-subject weights require full scope, source and sum 100')
    topics, totals, seen = {}, {}, set()
    for sid in sections:
        totals[sid] = dict(score=0, known=0, maximum=0, pending=0, blank=0)
    for p in data['points']:
        if not p['id'] or p['id'] in seen:
            raise ValueError('Duplicate or empty point ID')
        seen.add(p['id'])
        if not p.get('question') or not p.get('topic') or not p.get('source'):
            raise ValueError('Each point needs question, primary topic and source')
        if p['section'] not in sections or number(p['max']) <= 0:
            raise ValueError('Invalid section or maximum')
        if p['status'] not in ('scored', 'blank', 'pending', 'missing', 'excluded'):
            raise ValueError('Invalid point status')
        known = p['status'] in ('scored', 'blank')
        if known:
            if not 0 <= number(p['score']) <= p['max']:
                raise ValueError('Point score out of bounds')
            if p['status'] == 'blank' and p['score'] != 0:
                raise ValueError('Visible blank answers must score zero')
        elif p.get('score') is not None:
            raise ValueError('Pending, missing and excluded marks must be null')
        if p['status'] == 'excluded':
            continue
        t = topics.setdefault(p['topic'], dict(score=0, known=0, maximum=0, pending=0,
                                              blank=0, questions=set()))
        t['questions'].add(p['question'])
        for bucket in (t, totals[p['section']]):
            bucket['maximum'] += p['max']
            if known:
                bucket['score'] += p['score']
                bucket['known'] += p['max']
                if p['status'] == 'blank':
                    bucket['blank'] += p['max']
            else:
                bucket['pending'] += p['max']
    for sid, t in totals.items():
        if not math.isclose(t['maximum'], sections[sid]['max']):
            raise ValueError('Included point maxima do not match section: '+sid)
    total = None
    if weighted and all(t['pending'] == 0 for t in totals.values()):
        total = sum(t['score']/sections[sid]['max']*sections[sid]['weight']
                    for sid, t in totals.items())
    return sections, topics, totals, total


def esc(value):
    return html.escape(str(value), quote=True)


def fmt(value):
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def render(data):
    sections, topics, totals, total = analyse(data)
    def bar(label, t, extra=''):
        pct = t['score']/t['known']*100 if t['known'] else None
        value = '待評' if pct is None else fmt(pct)+'%'
        return (f'<div class="chart-row"><strong>{esc(label)}</strong><span>{value} · '
                f'{fmt(t["score"])}/{fmt(t["known"])} 已判分</span>'
                f'<div class="track" aria-hidden="true"><div style="width:{pct or 0:.6f}%"></div></div>'
                f'<small>已判上限 {fmt(t["known"])} / 納入上限 {fmt(t["maximum"])}；'
                f'待評 {fmt(t["pending"])}；未作答 {fmt(t["blank"])} {esc(extra)}</small></div>')
    charts = ''.join(bar(k, t, f'；涉及 {len(t["questions"])} 題'+
                         ('；少量題目，證據有限' if len(t['questions']) < 3 else ''))
                     for k, t in sorted(topics.items(), key=lambda kv:
                         kv[1]['score']/kv[1]['known'] if kv[1]['known'] else 2))
    section_rows = ''
    for sid, t in totals.items():
        s = sections[sid]
        contribution = '—'
        if 'weight' in s and not t['pending']:
            contribution = fmt(t['score']/s['max']*s['weight'])+' / '+fmt(s['weight'])
        section_rows += (f'<tr><th scope="row">{esc(s.get("label",sid))}</th>'
                         f'<td>{fmt(t["score"])} / {fmt(t["known"])}（已判）</td>'
                         f'<td>{fmt(s["max"])}</td><td>{fmt(t["pending"])}</td>'
                         f'<td>{contribution}</td></tr>')
    status_names = dict(scored='已評', blank='未作答', pending='待裁定', missing='缺失／不可辨', excluded='不計入')
    point_rows = ''
    for p in data['points']:
        score = '—' if p.get('score') is None else fmt(p['score'])
        point_rows += (f'<tr><th scope="row">{esc(p["id"])}<br>{esc(p["question"])}</th>'
                       f'<td>{esc(p["topic"])}</td><td>{score}/{fmt(p["max"])}<br>'
                       f'{status_names[p["status"]]}<br>{esc(p.get("basis","AI 建議分"))}</td>'
                       f'<td>{esc(p.get("evidence","未附原文"))}</td>'
                       f'<td>{esc(p.get("reason",""))}<br><strong>修正：</strong>{esc(p.get("correction","—"))}'
                       f'<br><small>{esc(p["source"])}</small></td></tr>')
    priorities = ''.join(f'<li><strong>{esc(p["title"])}</strong><p>{esc(p["evidence"])}</p>'
                         f'<p>教材：{esc(p["textbook"])}</p><p>練習：{esc(p["action"])}</p>'
                         f'<p>完成標準：{esc(p["criterion"])}</p></li>' for p in data.get('priorities', []))
    if len(data.get('priorities', [])) > 3:
        raise ValueError('At most three learning priorities')
    heading = fmt(total)+' / 100' if total is not None else '未提供完整整科加權總分'
    scope_label = {'full': '整套', 'paper': '單卷', 'partial': '單題／少量題'}[data['scope']]
    section_charts = ''.join(bar(sections[sid].get('label', sid), t) for sid, t in totals.items())
    return f'''<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(data['student'])} · 企會財學習評估</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f3ee;color:#152f38;font:16px/1.7 system-ui,"Microsoft JhengHei",sans-serif}}
main{{max-width:1100px;margin:auto;padding:36px 24px}}header{{border-top:6px solid #12675f;padding:24px 0}}h1{{font-size:32px;line-height:1.3}}h2{{font-size:22px}}h3{{font-size:18px}}small,.muted{{color:#4d6068}}section{{background:white;padding:24px;margin:20px 0;border:1px solid #dae1df;border-radius:12px}}.score{{font-size:36px;font-weight:750;color:#12675f}}.chart-row{{padding:14px 0;border-bottom:1px solid #e4e9e7}}.chart-row>strong{{display:block}}.chart-row>span{{float:right}}.track{{clear:both;height:14px;background:#e3ece9;margin:8px 0;border-radius:3px}}.track>div{{height:100%;background:#16796f;border-radius:3px}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;min-width:640px;font-size:14px}}th,td{{text-align:left;vertical-align:top;border-bottom:1px solid #dce4e1;padding:12px;overflow-wrap:anywhere;white-space:pre-line}}thead{{background:#edf4f1}}li{{margin-bottom:20px}}p{{overflow-wrap:anywhere}}summary{{cursor:pointer;font-weight:700}}@media(max-width:600px){{main{{padding:20px 12px}}section{{padding:16px}}h1{{font-size:26px}}.chart-row>span{{float:none}}}}@media print{{body{{background:white;color:black}}main{{max-width:none;padding:0}}section{{border-radius:0;break-inside:auto}}tr,.chart-row{{break-inside:avoid}}thead{{display:table-header-group}}.scroll{{overflow:visible}}table{{min-width:0}}details>div{{display:block!important}}.track{{print-color-adjust:exact}}}}
</style></head><body><main><header><p>BAFS · 學習評估</p><h1>{esc(data['student'])}的企會財評估</h1>
<p>{esc(data['exam'])} · {esc(data['date'])} · 範圍：{scope_label}</p>
<div class="score">{heading}</div><p>{esc(data['summary'])}</p><p class="muted">{esc(data['grade_note'])}</p></header>
<section><h2>成績與計分口徑</h2><p>{esc(data.get('weight_source','未設定整科權重；以下為所提交範圍的原始分。'))}</p>
<div class="scroll"><table><thead><tr><th>部分</th><th>已判得分</th><th>納入滿分</th><th>待評上限</th><th>整科貢獻／權重</th></tr></thead><tbody>{section_rows}</tbody></table></div>
<h3>各部分原始分得分率</h3><p class="muted">比較已判作答的得分率；各部分在整科的權重可能不同。</p>{section_charts}</section>
<section><h2>知識點得分率</h2><p>原始分加總：已判得分 ÷ 已判上限。未作答計零；待裁定及缺失不當零分。各條均以0–100%為相同尺度，並非整科加權分或能力等級。</p>{charts}
<p class="muted">每個得分點只歸入一個主要知識點；未考查的知識不代表不會。少量題目的得分率不宜外推為整個單元的掌握程度。</p></section>
<section><h2>優先補強</h2><ol>{priorities}</ol></section>
<section><details open><summary>逐題評分依據與修正</summary><div class="scroll"><table><thead><tr><th>得分點／題目</th><th>主要知識點</th><th>分數與性質</th><th>學生證據</th><th>理由、修正及來源</th></tr></thead><tbody>{point_rows}</tbody></table></div></details></section>
<footer><p>本報告為輔助學習評估；AI建議分與教師裁定以逐點標示為準。資料不足時不強行預測等級。</p></footer></main></body></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.ledger.resolve() == args.output.resolve():
        parser.error('Output must not overwrite the input ledger')
    result = render(json.loads(args.ledger.read_text(encoding='utf-8-sig')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result, encoding='utf-8')
    print(args.output)


if __name__ == '__main__':
    main()
