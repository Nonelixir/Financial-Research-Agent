# 第三方前端组件

[English](THIRD_PARTY.en.md)

随仓库提供 [Apache-2.0 许可](licenses/Apache-2.0.txt) 和 [AI Elements 来源与修改声明](licenses/AI-Elements-NOTICE.txt)，仅适用于对应第三方组件，不替项目选定许可证。

assistant-ui：`@assistant-ui/react`，MIT，项目 https://github.com/assistant-ui/assistant-ui 。

AI Elements Tool 与 Artifact 源码组件于 2026-10-10 从官方 Vercel registry 获取：
https://elements.ai-sdk.dev/api/registry/tool.json 、https://elements.ai-sdk.dev/api/registry/artifact.json 。
项目 https://github.com/vercel/ai-elements ，Apache-2.0。改动包括本地 import 与中文标签。

CodeBlock 为本地轻量实现，使用 react-markdown 和 highlight.js；基础 UI 使用 Radix。
实际依赖与版本以 package.json/package-lock.json 为准；保留源码许可证声明，不把第三方组件称为本项目原创。
