# Diagram maintenance and acceptance

[中文](../zh-CN/diagrams.md) · [README](../../README.en.md)

Code checked: 2026-10-12. Type architecture, nine nodes, static classic view, no invented deployment components.
[English HTML](../diagrams/architecture.en.html) · [中文 HTML](../diagrams/architecture.zh-CN.html).
Sources: [English JSON](../diagrams/architecture.en.json), [中文 JSON](../diagrams/architecture.zh-CN.json).

Evidence was inspected in api.py/workspace.py/agent.py/research_tools.py/data/sec.py/web.py/storage.py/filesystem.py/tools.py/verify/answer_stream.py and frontend.
Unavailable Python/shell execution is not drawn as active. This is a communication overview, not a prescribed model workflow; storage edges are simplified.

## Maintenance
Local browser acceptance screenshots/receipts are excluded from the public repository; published diagram files are the two HTML deliverables and JSON sources.


Inspect code facts first and update both JSON files with matching stable IDs and relationship semantics.
From the local archify Skill directory:

```bash
node bin/archify.mjs validate architecture <source.json> --quality showcase --json
node bin/archify.mjs deliver architecture <source.json> <output.html> --quality showcase --json
ARCHIFY_CHROME=/path/to/chrome node bin/archify.mjs visual-check <output.html> --json
```

Never edit delivered HTML directly; change source, validate and deliver again. Browser inspection does not modify the artifact.
Screenshots/receipts are acceptance sidecars for the current diagram, not retained historical development/evaluation reports.
The standalone HTML needs no project backend; download the documentation to follow local Markdown links.

## Current receipts

| Field | English | 中文 |
| --- | --- | --- |
| spec SHA256 | 79b0a1a3e75798b9e3b5acdff89643699031e4228142f32f59320efa12dc9f79 | 52210e19e1d04042afa2a48a081715d2a24e6ed7fa91d75cdfbd418032ff11bc |
| HTML SHA256 | 13ebd8e4e52bc5527eb0baf196ddfb8f2d977307aba7934aecaa2810aa522b68 | d6218f3f7f5dbd4a32e78e6b6714480fc70e229a296954b3bf5c562418106cfc |
| spec / HTML bytes | 4516 / 811221 | 4446 / 810405 |
| Validation | 9/9 showcase, zero errors/warnings | 9/9 showcase, zero errors/warnings |
| Browser evidence | passed | passed |
| Perceptual visual review | passed | passed |
| Geometry correction rounds | 1 | 1 |

Exact delivered HTML was checked at 1440×900, 1600×1000, 1920×1080 and 2048×1320 with no page overflow.
Light/dark screenshots at the endpoint sizes were inspected by the development agent, not an independent human reviewer.
This does not claim exhaustive end-to-end testing of export/search/focus interactions.
Machine receipts correctly retain visualReview=pending for automated checks; perceptual status comes from separately inspecting screenshots.
