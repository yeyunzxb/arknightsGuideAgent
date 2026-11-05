"""低速、限定清单的 PRTS 文章导入。只读取公开 /w/ 页面，不递归爬站。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import quote, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.knowledge import parse_markdown  # noqa: E402

ORIGIN = "https://prts.wiki"
AGENT = "ArknightsLocalKnowledge/1.0 (personal local RAG; limited page list)"
LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
OPERATOR_SECTIONS = {"特性", "获得方式", "属性", "天赋", "潜能提升", "技能", "后勤技能", "精英化材料", "技能升级材料", "模组"}


def compact(text):
    return re.sub(r"\s+", " ", text).strip()


def render_table(table, extra_context=""):
    """展开 rowspan/colspan，每条记录携带列名和技能上下文，避免数值失去条件。"""
    occupied, headers, context, lines = {}, [], "", []
    for row_index, row in enumerate(table.find_all("tr")):
        if row.find_parent("table") is not table:
            continue
        cells = row.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        col = 0
        records = []
        for cell in cells:
            while (row_index, col) in occupied:
                col += 1
            # 源站少量 HTML 包含 colspan="4;" 等非标准属性。
            def span(name, maximum):
                value = re.match(r"\d+", str(cell.get(name, 1)))
                return max(1, min(int(value[0]) if value else 1, maximum))
            width = span("colspan", 40)
            height = span("rowspan", 100)
            value = compact(cell.get_text(" ", strip=True))
            for r in range(row_index, row_index + height):
                for c in range(col, col + width):
                    occupied[r, c] = value
            records.append((col, width, value))
            col += width
        if all(cell.name == "th" for cell in cells):
            headers = [occupied.get((row_index, c), "") for c in range(col)]
            continue
        # 技能表的首行含技能名与回复/触发类型，后续每级记录重复携带。
        if row.find("big"):
            context = compact(extra_context + " " + row.get_text(" ", strip=True))
            lines.append("表格主题：" + context)
            continue
        if headers:
            pairs = []
            for start, width, value in records:
                if not value:
                    continue
                label = headers[start] if start < len(headers) and headers[start] else ("项目" if start == 0 else f"列{start + 1}")
                pairs.append(f"{label}：{value}")
            # 把跨行第一列（例如技能名）带入当前行。
            if records and records[0][0] > 0 and occupied.get((row_index, 0)):
                pairs.insert(0, (headers[0] or "项目") + "：" + occupied[row_index, 0])
            line = "；".join(pairs)
        else:
            line = " | ".join(value for _, _, value in records if value)
        if line:
            line = re.sub(r"Rank\s*Ⅲ", "专精三（Rank Ⅲ）", line)
            line = re.sub(r"Rank\s*Ⅱ", "专精二（Rank Ⅱ）", line)
            line = re.sub(r"Rank\s*Ⅰ", "专精一（Rank Ⅰ）", line)
            lines.append((context + "；" if context else "") + line)
    return "\n\n".join(lines)


def extract_page(html, category):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("#firstHeading")
    content = soup.select_one("#mw-content-text .mw-parser-output")
    if not title or not content:
        raise ValueError("未找到正文，可能是错误页或验证页；未导入")
    title = title.get_text(" ", strip=True)
    license_tag = soup.select_one('link[rel="license"]')
    if not license_tag or license_tag.get("href", "").rstrip("/") != LICENSE_URL.rstrip("/"):
        raise ValueError("页面许可与预期 CC BY-NC-SA 4.0 不一致；未导入")
    revision = re.search(r'"wgRevisionId"\s*:\s*(\d+)', html)
    lastmod = soup.select_one("#footer-info-lastmod")
    lastmod_text = compact(lastmod.get_text()) if lastmod else "页面未提供"
    date = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", lastmod_text)
    updated = f"{int(date[1]):04}-{int(date[2]):02}-{int(date[3]):02}" if date else "未标注（见抓取时间）"
    for box in list(content.select(".ak-cbox")):
        heading = box.select_one(".ak-cbox__title")
        if heading and compact(heading.get_text()) == "编辑须知":
            box.decompose()
    for link in content.select("a[title]"):
        if compact(link.get_text()) in {"限兑兑", "限", "兑"}:
            link.string = link["title"]
    for node in list(content.select("script, style, noscript, .toc, .mw-editsection, .navigation-not-searchable, .navbox, .nodesktop, input, button, audio, video, iframe")):
        if node.parent:
            node.decompose()
    for node in list(content.find_all(class_=re.compile(r"算法.*_2"))):
        node.decompose()
    for node in list(content.select('.mc-tooltips > [style*="display:none"], .mc-tooltips > [style*="display: none"]')):
        if node.find_parent("th") and re.search("信赖|潜能", node.get_text()):
            node.replace_with(NavigableString("（" + compact(node.get_text()) + "）"))
        else:
            node.decompose()
    for math_node in list(content.select(".mwe-math-element")):
        annotation = math_node.find("annotation", attrs={"encoding": "application/x-tex"})
        image = math_node.find("img")
        formula = annotation.get_text() if annotation else image.get("alt", "") if image else math_node.get_text()
        math_node.replace_with(NavigableString(" $" + formula + "$ "))
    for image in list(content.find_all("img")):
        link = image.find_parent("a")
        alt = image.get("alt", "") or (link.get("title", "") if link else "")
        image.replace_with(NavigableString(f" [图示：{alt}] " if alt and len(alt) < 80 else ""))
    sections, headings, blocks = [], [], []

    def flush():
        if not blocks:
            return
        text = "\n\n".join(blocks).strip()
        allowed = category != "干员" or headings and headings[0][1] in OPERATOR_SECTIONS
        if allowed and len(text) >= 20:
            sections.append({"heading": " / ".join(h[1] for h in headings) or "概述", "anchor": headings[-1][2] if headings else "", "text": text})
        blocks.clear()

    def visit(node):
        nonlocal headings
        if isinstance(node, NavigableString):
            value = compact(str(node))
            if value:
                blocks.append(value)
            return
        if not isinstance(node, Tag):
            return
        if node.name in {"h2", "h3", "h4", "h5", "h6"}:
            flush()
            level = int(node.name[1])
            name = compact(node.get_text(" ", strip=True))
            identifier = node.get("id") or (node.find(id=True) or {}).get("id", "")
            headings = [h for h in headings if h[0] < level] + [(level, name, identifier)]
        elif node.name == "table":
            stage = blocks[-1] if blocks and re.match(r"技能[123]（", blocks[-1]) else ""
            value = render_table(node, stage)
            if value:
                blocks.append(value)
        elif node.name in {"p", "li", "dt", "dd", "pre", "blockquote"} and not node.find(["table", "h2", "h3", "h4"]):
            value = compact(node.get_text(" ", strip=True))
            if value:
                blocks.append(value)
        else:
            for child in node.children:
                visit(child)
    visit(content)
    flush()
    # 响应式布局可能重复相同表格/段落；按完整片段去重。
    seen, unique = set(), []
    for section in sections:
        key = (section["heading"], section["text"])
        if key not in seen:
            seen.add(key)
            unique.append(section)
    if not unique:
        raise ValueError("没有提取到适用的正文段落；未导入")
    return {"title": title, "updated": updated, "revision": revision[1] if revision else None,
            "last_modified": lastmod_text, "sections": unique}


def make_documents(page, entry, fetched):
    url = ORIGIN + "/w/" + quote(page["title"], safe="")
    documents = {}
    for index, section in enumerate(page["sections"], 1):
        source = url + ("#" + quote(section["anchor"], safe="") if section["anchor"] else "")
        title = f'PRTS · {page["title"]} · {section["heading"]}'
        meta = {"title": title, "category": entry["category"], "tags": list(dict.fromkeys([page["title"], *entry.get("tags", []), section["heading"]])),
                "source": source, "updated": page["updated"],
                "server": "PRTS 中文站页面；页面涉及的服务器、版本和修正说明以正文为准",
                "license": "CC BY-NC-SA 4.0", "license_url": LICENSE_URL,
                "fetched_at": fetched, "revision_id": page["revision"], "original_title": page["title"],
                "attribution": "PRTS Wiki 页面贡献者；贡献者历史见原站；游戏原始素材权利归原权利人",
                "extraction_note": "正文抽取、表格转带列名记录、按章节拆分；Rank I/II/III 规范为专精一/二/三；未用模型补写。图片、范围图、视频及交互计算器未转录。抓取时间不是资料适用版本。"}
        # 许可与抓取说明保存在头部，不加入检索正文，避免来源声明被误检索为攻略。
        text = ("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n\n"
                + f"# {title}\n\n{section['text']}\n")
        filename = f"{index:03}-{re.sub(r'[<>:\"/\\|?*]', '-', section['heading'])[:90]}.md"
        parse_markdown(text, filename)
        if len(text.encode("utf-8")) > 1_000_000:
            raise ValueError("单节超过 1 MB，请进一步拆分")
        documents[filename] = text
    return documents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "scripts/prts-pages.json")
    parser.add_argument("--refresh", action="store_true", help="更新之前由此脚本管理的资料；本地修改冲突会跳过")
    parser.add_argument("--from-cache", action="store_true", help="使用已存档 HTML 重新整理，不访问网站")
    parser.add_argument("--delay", type=float, default=3, help="请求间隔秒数，最小 3")
    args = parser.parse_args()
    if args.from_cache:
        args.refresh = True
    entries = json.loads(args.manifest.read_text(encoding="utf-8"))
    destination, archive = ROOT / "knowledge/prts", ROOT / ".runtime/prts"
    destination.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    report_path = destination / "import-report.json"
    previous = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {"pages": []}
    old_pages = {p["requested_title"]: p for p in previous["pages"]}
    # 使用 UTC+8 固定时区，避免 Windows 缺少 IANA tzdata。
    from datetime import timezone, timedelta
    fetched = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    report = {"processed_at": fetched, "license": LICENSE_URL, "pages": list(old_pages.values()), "errors": []}
    with httpx.Client(timeout=45, headers={"User-Agent": AGENT}, follow_redirects=True) as client:
        if args.from_cache:
            robots_text = (archive / "robots.txt").read_text(encoding="utf-8")
        else:
            response = client.get(ORIGIN + "/robots.txt")
            response.raise_for_status()
            response.encoding = "utf-8"
            robots_text = response.text
        robots = RobotFileParser()
        robots.parse(robots_text.splitlines())
        (archive / "robots.txt").write_text(robots_text, encoding="utf-8")
        delay = max(3, args.delay, robots.crawl_delay(AGENT) or 0)
        for entry in entries:
            title = entry["title"]
            old = old_pages.get(title)
            if old and not args.refresh:
                print(f"跳过已导入页面：{title}", flush=True)
                continue
            url = ORIGIN + "/w/" + quote(title, safe="")
            if not robots.can_fetch(AGENT, url):
                report["errors"].append({"title": title, "error": "robots.txt 不允许抓取"})
                continue
            safe_title = re.sub(r'[<>:\"/\\|?*]', '-', title)
            if not args.from_cache:
                time.sleep(delay)
            try:
                if args.from_cache:
                    response = httpx.Response(200, content=(archive / (safe_title + ".html")).read_bytes(), request=httpx.Request("GET", url))
                else:
                    response = client.get(url)
                if response.status_code in (403, 429):
                    raise RuntimeError(f"站点返回 {response.status_code}，停止后续请求；请稍后再试")
                response.raise_for_status()
                if urlparse(str(response.url)).hostname != "prts.wiki":
                    raise ValueError("页面跳转到其他域名，未导入")
                page = extract_page(response.content.decode("utf-8"), entry["category"])
                page_fetched = old.get("fetched_at", fetched) if args.from_cache and old else fetched
                documents = make_documents(page, entry, page_fetched)
                folder = destination / re.sub(r'[<>:\"/\\|?*]', '-', title)
                folder.mkdir(exist_ok=True)
                old_hashes = old.get("file_hashes", {}) if old else {}
                # 刷新前检查所有旧文件，保护手工修改和未知同名文件。
                for filename, content in documents.items():
                    target = folder / filename
                    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != old_hashes.get(filename):
                        raise ValueError(f"本地文件存在或已修改，保留原文件并跳过：{filename}")
                hashes = {}
                for filename, content in documents.items():
                    target = folder / filename
                    target.write_text(content, encoding="utf-8")
                    hashes[filename] = hashlib.sha256(target.read_bytes()).hexdigest()
                # 源站章节重命名可能留下旧文档；不自动删除，报告过期资料供用户检查。
                stale = sorted(set(old_hashes) - set(hashes))
                if not args.from_cache:
                    (archive / (safe_title + ".html")).write_bytes(response.content)
                item = {"requested_title": title, "resolved_title": page["title"], "source": str(response.url),
                        "revision": page["revision"], "updated": page["updated"], "fetched_at": page_fetched,
                        "documents": len(documents), "file_hashes": hashes, "stale_files": stale}
                report["pages"] = [p for p in report["pages"] if p["requested_title"] != title] + [item]
                print(f"已导入：{title} → {len(documents)} 份章节文档（修订 {page['revision']}）", flush=True)
            except Exception as exc:
                report["errors"].append({"title": title, "error": str(exc)})
                print(f"失败：{title}：{exc}", flush=True)
                if isinstance(exc, (RuntimeError, httpx.RequestError)):
                    break
            finally:
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"导入记录：{report_path}", flush=True)
    if report["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
