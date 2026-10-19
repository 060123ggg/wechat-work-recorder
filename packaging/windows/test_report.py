"""在 Actions 页面展示跨平台测试证据，不改变 pytest 的退出状态。"""
import os
from pathlib import Path
from xml.etree import ElementTree


def main():
    report = Path('test-results.xml')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if not report.exists() or not summary:
        return
    root = ElementTree.parse(report).getroot()
    lines = ['## 自动测试结果', '']
    for suite in root.iter('testsuite'):
        lines.append(f"tests={suite.get('tests')}, failures={suite.get('failures')}, errors={suite.get('errors')}, skipped={suite.get('skipped')}")
    for case in root.iter('testcase'):
        for node in list(case):
            if node.tag in ('failure', 'error'):
                lines.extend(['', case.get('classname', '') + '::' + case.get('name', ''),
                              '```text', (node.text or node.get('message', ''))[:6000], '```'])
    with Path(summary).open('a', encoding='utf-8') as output:
        output.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
