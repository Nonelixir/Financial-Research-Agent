# 前端与语言交互

[English](../en/frontend.md) · [README](../../README.md)

按当前代码核对：2026-10-12。

## 技术与职责

React 19 / TypeScript / Vite；assistant-ui 提供聊天组件与 external-store runtime，AI Elements 提供 Tool/Artifact 源码组件。
不是完整采用 AI SDK 服务端消息协议；`frontend/src/api.ts` 解析本项目 SSE，`main.tsx` 维护会话状态。
Radix、react-markdown/remark-gfm、highlight.js、Lucide 等用于基本组件和渲染。第三方来源和许可证见 [说明](../../frontend/THIRD_PARTY.md)。

支持会话列表/标题过滤、新建/重命名/删除、用户消息编辑、重新生成、复制、停止、自动滚动、主题、可选公司/年份/表单/strict。
标题搜索只是前端包含匹配，不是全消息检索。UI 只提供 10-K/10-Q 勾选，Agent 开放工具可发现 8-K。
研究样本成员和选中公司不是整个行业；页面展示非穷尽样本，点击查看支持来源。

## 流式行为

状态按 tool_call_id（无时 phase）分组，展示 active/complete/warning；sources/plan/sample/artifact 动态进入工作台。
正文不是逐 token 原样输出：后端解析结构化 Answer，只提交已闭合且校验通过的 Claim。
所以有时状态推进而正文暂为空；思考和未闭合 JSON 不作为正文发布。
前缀冻结避免同段反复消失，但模型重试改写前缀仍可能失败，recoverable 恢复有重复段落风险；不是这些体验 bug 已全部修复。

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
