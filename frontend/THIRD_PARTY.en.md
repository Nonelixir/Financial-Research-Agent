# Third-party frontend components

[中文](THIRD_PARTY.md)

The repository includes the [Apache-2.0 license](licenses/Apache-2.0.txt) and [AI Elements attribution/modification notice](licenses/AI-Elements-NOTICE.txt). These apply to the corresponding third-party components, not a license selection for the whole project.

assistant-ui: `@assistant-ui/react`, MIT, https://github.com/assistant-ui/assistant-ui .

AI Elements Tool and Artifact source components were retrieved on 2026-10-10 from the official Vercel registry:
https://elements.ai-sdk.dev/api/registry/tool.json and https://elements.ai-sdk.dev/api/registry/artifact.json .
Project: https://github.com/vercel/ai-elements , Apache-2.0. Local changes include imports and Chinese labels.

CodeBlock is a local lightweight implementation using react-markdown and highlight.js; supporting UI primitives use Radix.
package.json/package-lock.json are authoritative for dependency versions. Retain upstream license notices; do not present third-party components as original work.
