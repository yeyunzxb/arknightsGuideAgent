# PRTS · 明日方舟 RAG 问答终端

一个可本地一键启动、无需登录的明日方舟知识库问答应用。前端 Vue 3，后端 FastAPI，使用 LangChain LCEL 组织 RAG，DeepSeek 负责生成回答。初始知识仅为教学小样本，你可以逐步添加自己的资料。

## 一键启动

环境：Python **3.11+**、Node.js **18.19+**（推荐 22 LTS）。首次启动需要联网下载依赖；本地检索无需 GPU、Embedding API 或模型下载。

**Windows：双击根目录 `start.bat`**，或者在 PowerShell 中执行：

```powershell
.\start.bat
```

**macOS / Linux：**

```bash
sh start.sh
```

启动器自动创建 `.venv`、安装依赖、同时启动前后端并打开浏览器。

- 应用：<http://127.0.0.1:5173>
- FastAPI 交互文档：<http://127.0.0.1:8000/docs>
- 在启动终端按 **Ctrl+C**，同时关闭两个服务。
- `start.bat --no-browser`：启动但不打开浏览器。
- `start.bat --install-only`：只准备依赖。

进入应用后，点击“配置连接”，填写你自己的 DeepSeek 密钥，点击“验证连接并获取模型”，成功后从返回的真实模型列表中选择模型并提问。未验证时不展示预设模型；修改或清空密钥会清除旧列表，需要重新验证。模型列表从 DeepSeek 官方 `/models` 获取，模型名称会随官方服务调整。

页面右上角可切换深色与浅色主题，选择会保存在当前浏览器中；首次访问跟随系统外观。首页只保留问候与输入框，手机上可通过左上角菜单访问知识库和历史对话。

密钥只保存在当前页面内存，不进入 localStorage、知识库或配置文件，刷新页面后需重新填写。后端仅在当前请求中使用密钥，固定请求 `https://api.deepseek.com`，不支持其他供应商或自定义代理地址。对话记录保存于浏览器 localStorage，可在侧栏逐条删除。问题、最近历史与相关文档片段会发送给 DeepSeek；本地运行不等于离线模型。

## 添加知识

已提供 PRTS 网站资料采集工具及首批整理文档。范围、来源许可、更新命令见 [PRTS 导入说明](docs/prts-import.md)；默认文章清单在 `scripts/prts-pages.json`。

完整格式见 [知识库模板](templates/knowledge-template.md) 和 [格式说明](docs/knowledge-format.md)。

```markdown
---
title: "资料标题"
category: "干员"
tags: ["关键词", "别名"]
source: "可追溯的链接或出处"
updated: "2026-11-05"
server: "国服；适用版本"
---

# 资料标题

## 概述
填写已经核实的内容。

## 详细说明
填写技能、机制、适用条件和限制。
```

两种添加方式：

1. 页面“知识库”→“下载知识库模板”→填写→“导入 Markdown”，自动更新索引。
2. 把 `.md` 文件放入根目录 `knowledge/`（支持子目录），点击“重建索引”或重启后端。

网页导入不会覆盖同名文件。修改或删除现有资料时，在本地编辑/删除对应文件，然后重建索引。无效文档会被跳过并显示具体原因。索引在内存中，启动时从磁盘资料重建，不使用不安全的 pickle 索引文件。

## 实现与学习

```text
Vue 3 → POST /api/chat → FastAPI
                           ↓
Markdown → Document → 文档切块 → TF-IDF 检索
                           ↓
本轮原文 + 最近历史 + 问题 → ChatPromptTemplate
                           ↓
             ChatOpenAI（DeepSeek 兼容协议）
                           ↓
                StrOutputParser → SSE → Vue
```

这是**固定检索流程的 RAG 问答助手**：每轮由程序先检索，再调用模型。没有让模型自行决定工具调用或执行游戏操作。它直接对应原学习指南 11；同时使用 01/02 的提示词与 LCEL、05 的异步流式输出、06 的历史隔离、09/10 的切块检索，以及 15 的引用与拒答思想。逐文件讲解和练习见 [学习对照](docs/learning-map.md)。

TF-IDF 是本地词面检索，不是预训练语义 Embedding。每个文档块 700 字、重叠目标 100 字，字符 1～3 gram，默认取相似度不低于 0.06 的前 4 块。分数不是置信概率，低分过滤也不能证明内容足够。没有候选直接拒答且不请求模型；有候选时依靠提示词要求模型判断证据是否充分并标引用，仍可能出现不恰当引用，需要检查原文。短追问会拼接最近两条用户问题辅助检索，复杂指代可能仍需用户补充完整对象。

## 目录

```text
backend/app/main.py        FastAPI 路由与错误脱敏
backend/app/schemas.py     请求结构与校验
backend/app/knowledge.py   Markdown、元数据、切块、本地索引
backend/app/rag.py         提示词、模型、LCEL、SSE
backend/tests/            无付费调用的测试
frontend/src/App.vue      对话、知识库、连接设置与深浅色主题
frontend/src/api.js       fetch 与 SSE 分片解析
knowledge/                自己维护的知识库
templates/                文档模板（不参与检索）
docs/                     格式与学习说明
scripts/launch.py         安装、端口检查、前后端生命周期
```

## 单独开发与验证

启动器准备好依赖后，分别在两个终端运行：

```powershell
# 后端
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# 前端
cd frontend
npm run dev
```

项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
```

测试涵盖文档格式、路径校验、同名保护、重启后重新检索、切块来源、空库拒答、LCEL 流式协议、历史与引用、密钥脱敏及模型发现。模型输出使用测试替身，不消耗真实 API 额度，也不证明真实模型的事实正确性。真实 DeepSeek 的端到端体验需要在页面填入你自己的有效密钥验证。

前后端通过 `/api` 分离：Vite 将请求代理到 8000 端口；`npm run build` 产物在 `frontend/dist/`，`npm run preview` 同样可代理本地后端。当前定位为本机工具，服务仅绑定 127.0.0.1，不含用户鉴权或公网部署配置。

## 常见问题

- **首次安装较慢/失败**：检查网络后重新启动；成功安装的依赖会复用。不要把 API Key 写到命令行或提交到代码仓库。
- **端口占用**：关闭原来的 PRTS 启动终端或占用 5173/8000 的程序后重试；启动器不会主动杀掉其他进程。
- **模型调用失败**：在设置中验证密钥并刷新模型列表，检查 DeepSeek 余额与网络。
- **资料不足**：查看知识库是否导入成功、展开检索参考，用资料中的名称与别名提问；TF-IDF 不能保证识别不共享字符的同义表达。
- **资料改了但回答没变**：点击重建索引，并确认引用指向新原文。历史回答不作为本轮事实来源。

## 官方参考

- [DeepSeek API 与当前模型](https://api-docs.deepseek.com/)
- [DeepSeek 模型发现接口](https://api-docs.deepseek.com/api/list-models/)
- [LangChain ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai)

代码沿用学习指南的 ChatOpenAI 兼容适配方式，并关闭思考模式，仅消费标准正文流。若以后需要 DeepSeek 特有的 reasoning_content、思考过程或专用工具行为，优先改用官方 LangChain DeepSeek 集成，并补充兼容性测试。
