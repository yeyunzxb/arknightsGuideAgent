"""学习 09/10：Markdown → Document → 切块 → 本地 TF-IDF → 可追溯检索。"""
import re
import threading
import math
from collections import Counter
from pathlib import Path

import yaml
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

CATEGORIES = {"干员", "关卡", "机制", "养成", "活动", "其他"}


class TfidfIndex:
    """稀疏 TF-IDF：平滑 IDF、对数 TF、L2 归一化；无需大型科学计算依赖。"""
    @staticmethod
    def terms(text):
        text = re.sub(r"\s+", " ", text.lower())
        return Counter(text[i:i + n] for n in (1, 2, 3) for i in range(len(text) - n + 1))

    def __init__(self, texts):
        counts = [self.terms(text) for text in texts]
        frequency = Counter(term for count in counts for term in count)
        self.idf = {term: math.log((1 + len(texts)) / (1 + count)) + 1 for term, count in frequency.items()}
        self.vectors = [self.vector(count) for count in counts]

    def vector(self, count):
        weighted = {term: (1 + math.log(value)) * self.idf[term] for term, value in count.items() if term in self.idf}
        norm = math.sqrt(sum(value * value for value in weighted.values()))
        return {term: value / norm for term, value in weighted.items()} if norm else {}

    def scores(self, query):
        vector = self.vector(self.terms(query))
        return [sum(value * doc.get(term, 0) for term, value in vector.items()) for doc in self.vectors]


def parse_markdown(content: str, filename: str) -> Document:
    content = content.lstrip("\ufeff").replace("\r\n", "\n")
    match = re.match(r"\A---\n(.*?)\n---(?:\n|$)(.*)\Z", content, re.S)
    if not match:
        raise ValueError("文档需要 YAML 头部（以 --- 包围），请参考知识库模板")
    try:
        meta = yaml.safe_load(match[1])
    except yaml.YAMLError as exc:
        raise ValueError("YAML 头部格式不正确") from exc
    if not isinstance(meta, dict):
        raise ValueError("YAML 头部必须是字段映射")
    for field in ("title", "category", "source", "updated", "server"):
        if not isinstance(meta.get(field), str) or not meta[field].strip():
            raise ValueError(f"头部缺少文本字段 {field}（日期请使用引号）")
    if meta["category"] not in CATEGORIES:
        raise ValueError("category 必须为：" + "、".join(sorted(CATEGORIES)))
    tags = meta.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise ValueError("tags 必须是文本数组")
    body = match[2].strip()
    if not body:
        raise ValueError("文档正文不能为空")
    # 仅保留规范字段，不把任意 YAML 对象传进提示词。
    metadata = {k: meta[k].strip() for k in ("title", "category", "source", "updated", "server")}
    metadata.update(filename=filename, tags=tags)
    # 网站导入的溯源/许可字段随文档块保留，但不加入 TF-IDF 正文。
    for field in ("license", "license_url", "fetched_at", "revision_id", "original_title", "attribution", "extraction_note"):
        if isinstance(meta.get(field), str):
            metadata[field] = meta[field]
    return Document(page_content=body, metadata=metadata)


class KnowledgeStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.documents = []
        self.chunks = []
        self.errors = []
        self.vectorizer = None
        self.rebuild()

    def rebuild(self):
        with self.lock:
            documents, errors = [], []
            for path in sorted(self.directory.rglob("*.md")):
                if path.is_symlink() or not path.resolve().is_relative_to(self.directory):
                    continue
                try:
                    if path.stat().st_size > 1_000_000:
                        raise ValueError("文件超过 1 MB")
                    documents.append(parse_markdown(path.read_text(encoding="utf-8"), path.relative_to(self.directory).as_posix()))
                except (ValueError, OSError) as exc:
                    errors.append({"filename": path.relative_to(self.directory).as_posix(), "error": str(exc)})
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=700, chunk_overlap=100, add_start_index=True,
                separators=["\n## ", "\n\n", "\n", "。", "；", "", ],
            )
            chunks = splitter.split_documents(documents)
            for i, chunk in enumerate(chunks):
                chunk.metadata["chunk_id"] = i + 1
            vectorizer = None
            if chunks:
                # 字符 1~3 gram 适合中文，不下载模型。分数是词面相似度，不是置信度。
                vectorizer = TfidfIndex([
                    f'{c.metadata["title"]} {" ".join(c.metadata["tags"])} {c.page_content}' for c in chunks
                ])
            # 完成新索引后一次性替换；并发查询不会读到半成品。
            self.documents, self.chunks, self.errors = documents, chunks, errors
            self.vectorizer = vectorizer
            return self.stats()

    def stats(self):
        with self.lock:
            return {"documents": len(self.documents), "chunks": len(self.chunks), "errors": self.errors,
                    "files": [dict(d.metadata, characters=len(d.page_content)) for d in self.documents]}

    def search(self, question: str, top_k: int = 4):
        with self.lock:
            if self.vectorizer is None:
                return []
            scores = self.vectorizer.scores(question)
            order = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
            return [dict(self.chunks[i].metadata, text=self.chunks[i].page_content, score=round(float(scores[i]), 4))
                    for i in order[:top_k] if scores[i] >= 0.06]

    def add(self, filename: str, content: str):
        if not re.fullmatch(r"[\w\-\u4e00-\u9fff][\w\-.\u4e00-\u9fff ]*\.md", filename, re.I):
            raise ValueError("文件名只能包含中英文、数字、空格、点、下划线和短横线，且以 .md 结尾")
        if len(content.encode("utf-8")) > 1_000_000:
            raise ValueError("文件超过 1 MB")
        parse_markdown(content, filename)
        with self.lock:
            path = self.directory / filename
            # 不覆盖已有资料，也不跟随符号链接。
            with path.open("x", encoding="utf-8") as file:
                file.write(content)
            return self.rebuild()
