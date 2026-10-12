# 架构图维护与验收

[English](../en/diagrams.md) · [README](../../README.md)

当前代码核对：2026-10-12。图类型 architecture，9 个节点，默认静态、classic 风格，无虚构部署节点。
[中文 HTML](../diagrams/architecture.zh-CN.html) · [英文 HTML](../diagrams/architecture.en.html)。
图源：[中文 JSON](../diagrams/architecture.zh-CN.json)、[English JSON](../diagrams/architecture.en.json)。

图对应 api.py/workspace.py/agent.py/research_tools.py/data/sec.py/web.py/storage.py/filesystem.py/tools.py/verify/answer_stream.py 与前端。
不绘制尚不可用的 Python/shell 执行器。图是组件通信概览，不是规定模型步骤的 workflow，也不展开全部读写关系。

## 维护

先核对代码事实，同时修改两份 JSON；保持节点 ID、连线语义与语言版本对应。
在本地 archify Skill 目录执行：

```bash
node bin/archify.mjs validate architecture <source.json> --quality showcase --json
node bin/archify.mjs deliver architecture <source.json> <output.html> --quality showcase --json
ARCHIFY_CHROME=/path/to/chrome node bin/archify.mjs visual-check <output.html> --json
```

验证通过后不要手工改 HTML；只改图源后重新交付。浏览器检查不修改图。
验收截图与机器回执仅是当前架构图的伴随证据，不是历史开发/评测报告。
伴随验收文件仅本地保存，不随公开仓库发布；公开内容为两份 HTML 和 JSON 图源。
导出图片不依赖项目后端；独立 HTML 可本地打开，但 Markdown 文件链接需下载文档后查看。

## 当前回执

| 字段 | 中文 | English |
| --- | --- | --- |
| spec SHA256 | 52210e19e1d04042afa2a48a081715d2a24e6ed7fa91d75cdfbd418032ff11bc | 79b0a1a3e75798b9e3b5acdff89643699031e4228142f32f59320efa12dc9f79 |
| HTML SHA256 | d6218f3f7f5dbd4a32e78e6b6714480fc70e229a296954b3bf5c562418106cfc | 13ebd8e4e52bc5527eb0baf196ddfb8f2d977307aba7934aecaa2810aa522b68 |
| spec / HTML bytes | 4446 / 810405 | 4516 / 811221 |
| 验证 | 9/9 showcase，0 错误/警告 | 9/9 showcase，0 错误/警告 |
| 浏览器证据 | passed | passed |
| 图片视觉检查 | passed | passed |
| 布局修正轮次 | 1 | 1 |

浏览器检查使用实际交付 HTML，1440×900、1600×1000、1920×1080、2048×1320 均无页面溢出，
并截图检查 1440/2048 下明暗主题。人工式视觉复核由开发 Agent 查看实际截图，非独立人类审核；
未将图的导出、搜索、focus 等所有交互当作端到端验收已完成。
机器回执仍保持 visualReview=pending，这是工具对自动检查的正确表述；上表视觉判断来自独立查看截图。
