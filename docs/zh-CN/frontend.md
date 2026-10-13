# 前端与语言交互

[English](../en/frontend.md) · [README](../../README.md)

按当前代码核对：2026-10-13。

## 技术与职责

React 19 / TypeScript / Vite；assistant-ui 提供聊天组件与 external-store runtime，AI Elements 提供 Tool/Artifact 源码组件。
不是完整采用 AI SDK 服务端消息协议；`frontend/src/api.ts` 解析本项目 SSE，`main.tsx` 维护会话状态。
Radix、react-markdown/remark-gfm、highlight.js、Lucide 等用于基本组件和渲染。第三方来源和许可证见 [说明](../../frontend/THIRD_PARTY.md)。

支持会话列表/标题过滤、新建/重命名/删除、用户消息编辑、重新生成、复制、停止、自动滚动、主题、可选公司/年份/表单/strict。
标题搜索只是前端包含匹配，不是全消息检索。UI 只提供 10-K/10-Q 勾选，Agent 开放工具可发现 8-K。
研究样本成员和选中公司不是整个行业；页面展示非穷尽样本，点击查看支持来源。

## 流式行为

状态按 tool_call_id（无时 phase）分组，展示 active/complete/warning；sources/plan/sample/artifact 动态进入工作台。
正文不是逐 token 原样输出：后端解析结构化 Answer，整份校验通过才提交正文。
所以有时状态推进而正文暂为空；思考和未闭合 JSON 不作为正文发布。
工具进度实时展示，正文整份校验通过后显示；重试期间正文不冻结，失败恢复只选最新候选，避免合并多个版本造成重复。

## 引用与产物

Claim 文末追加编号按钮，点击 API 加载来源侧栏：原文/值、定位、日期、URL、hash（存在时）。
模型若自己写引用文本，可能形成多余标签；不是句内细粒度 span UI。
派生表达式可显示，但输入链未实现完整可点击浏览；不能把首输入 SourceRef 当全部来源。
产物页面展示 Markdown/JSON/表格、营收柱图、下载和展开；图表是表格视图，不是任意模型可执行应用。
无安全的交互 HTML artifact、代码执行、文件上传或通用图像生成入口。

## 中英文

`i18n.tsx` / `localization.py` / `prompts.toml` 分别处理 UI、服务端状态、模型语言要求。
English/中文切换写 localStorage，后续请求 Scope.language 同步，计划、回答、报告标题/季度 sheet 使用目标语言。
历史消息、原文引用、证券代码、来源 ID 不翻译。部分注册标签仍用 key，未知状态可能展示原始字符串。
年度工作簿仍使用固定 Data/Provenance 和其模板文案，不承诺任意二进制产物全量翻译。
图的 viewer 是独立 HTML，中文/英文分别入口，不与对话 UI 的 localStorage 绑定。

## 构建维护

`npm --prefix frontend ci`，`npm --prefix frontend run build`，输出 `src/finagent/static/workspace/`。
生产 FastAPI 同源提供 /assets，无独立 Node。首次生成 assets 后应重启服务以注册挂载。
改 SSE 字段要同步 types/API/state；改 UI 文案同步语言表；不要绕过后端校验直接显示模型 scratch text。

普通对话的 message 独立显示；会话持久化同时保存该文本，刷新后仍可阅读，无需虚构引用。

回答正文在整份校验通过后发布，工具/status 进度仍实时展示；重试可改写未发布草稿，失败恢复只保留最新候选。普通行业回答保持简洁以适配普通输出预算。此前 10 题成绩早于这次发布流程变更。
