import importlib.util
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.knowledge import parse_markdown

spec = importlib.util.spec_from_file_location("import_prts", Path(__file__).resolve().parents[2] / "scripts/import_prts.py")
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


def page(body, license_url=importer.LICENSE_URL):
    return f'''<html><head><link rel="license" href="{license_url}"></head>
    <script>var conf={{"wgRevisionId":123}};</script>
    <h1 id="firstHeading">测试干员</h1><div id="mw-content-text"><div class="mw-parser-output">{body}</div></div>
    <li id="footer-info-lastmod">此页面最后编辑于2026年11月1日</li></html>'''


def test_header_and_table_context_and_provenance():
    html = page('''<div class="mw-heading"><h2 id="技能">技能</h2></div><div>技能1（精英0开放）</div>
      <table><tr><td><big>测试技能</big></td><td>自动回复</td></tr>
      <tr><th>等级</th><th>描述</th><th>消耗</th></tr>
      <tr><td>Rank Ⅲ</td><td>攻击力+90%</td><td>20</td></tr></table>
      <table class="nodesktop"><tr><td>不该重复导入</td></tr></table>
      <div class="mw-heading"><h2>干员档案</h2></div><p>故事内容不在本次战斗资料范围。</p>''')
    result = importer.extract_page(html, "干员")
    assert result["updated"] == "2026-11-01" and result["revision"] == "123"
    assert len(result["sections"]) == 1
    text = result["sections"][0]["text"]
    assert "技能1（精英0开放） 测试技能" in text
    assert "专精三（Rank Ⅲ）" in text and "消耗：20" in text
    assert "故事内容" not in text and "不该重复导入" not in text
    docs = importer.make_documents(result, {"category": "干员", "tags": ["测试"]}, "2026-11-05T12:00:00+08:00")
    doc = parse_markdown(next(iter(docs.values())), "test.md")
    assert doc.metadata["license"] == "CC BY-NC-SA 4.0"
    assert doc.metadata["source"].endswith("#%E6%8A%80%E8%83%BD")
    assert "license_url" in doc.metadata and "fetched_at" in doc.metadata
    assert "抓取时间" not in doc.page_content


def test_malformed_colspan_and_rowspan():
    soup = BeautifulSoup('''<table><tr><th>职业</th><th>阶段</th><th>数值</th></tr>
        <tr><td rowspan="2">术师</td><td>精英1</td><td colspan="1;">50</td></tr>
        <tr><td>精英2</td><td>100</td></tr></table>''', "html.parser")
    text = importer.render_table(soup.table)
    assert "职业：术师；阶段：精英2；数值：100" in text


def test_attribute_conditions_not_removed_with_hidden_tooltips():
    html = page('''<h2>属性</h2><table><tr><th>项目</th><th>精英2满级<span class="mc-tooltips"><span style="display:none">不包括信赖及潜能加成</span></span></th></tr>
       <tr><td>攻击</td><td>612</td></tr></table>''')
    text = importer.extract_page(html, "干员")["sections"][0]["text"]
    assert "不包括信赖及潜能加成" in text and "612" in text


def test_error_or_changed_license_is_rejected():
    with pytest.raises(ValueError, match="正文"):
        importer.extract_page("<html>access denied</html>", "机制")
    with pytest.raises(ValueError, match="许可"):
        importer.extract_page(page("<h2>技能</h2><p>足够长度的测试段落，包含技能回复和消耗说明。</p>", "https://example.com/"), "机制")
