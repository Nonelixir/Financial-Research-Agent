# SEC、网页与检索

[English](../en/sources-retrieval.md) · [README](../../README.md)

按当前代码核对：2026-10-12。

## SEC 接入

代码：`data/sec.py`。公司来自 SEC ticker 目录，本地 companies 可存别名；CIK 归一为十位、ticker 大写。
公司名解析只确认主体，不证明行业归属。行业样本需要网页/财报已登记证据，不能仅由名称搜索推出。

- submissions recent + 按请求年份重叠读取的 historical files 分片；去重、按披露日期排序。无年份不遍历所有历史分片。
- 文本目录支持 10-K/10-Q/8-K；8-K 按 filing_date 年份，其他使用 report_date（缺失时 filing_date）。
- list_filings 支持 filed_from/to，提供 accession；目录获取不等于全部正文下载。
- 主文件缓存；附件通过 accession-index.html 声明文件目录读取，禁止猜文件名。仅 HTML/TXT，无 PDF/OCR。
- Company Facts 解析保留数值、单位、taxonomy/concept、start/end、fy/fp、accession/form/filed/frame；非有限数字不入库。
- 数值事实解析接受 10-K/10-Q（含 /A），不是所有表单或所有 SEC 标签都可比。

## 缓存与网络

ticker/附件索引/正文通常缓存 86400 秒，submissions 3600 秒，Company Facts 21600 秒。
缓存写入 source_cache，并按 URL+SHA256 保存 source_snapshots；故障可回退现有缓存并给出警告，不补零。
SEC 使用真实联系身份 User-Agent，HTTPS allowlist、无任意重定向，默认每 client 5 请求/秒、请求 30 秒。
多个 Agent client 并发并没有全进程统一 SEC 限速。缓存可用不等于原站当前可访问。

## FTS5 与分页

`retrieval/ingest.py` 将 HTML 块转成 paragraph，保存 section、paragraph_index、dom_path、exact_quote、quote hash。
表格目前主要扁平文本，无法保证行/列/金额单位结构被完整保留。
`retrieval/query.py` 使用 SQLite FTS5 unicode61 分词、OR 关键词与 BM25，不是向量相似度或语义检索。
中文常见财务词通过小型词典扩展为英文；英文直接按词检索，未知中文领域词召回可能差。

默认自主工具每次分页取片段，可反复检索/读取；没有整轮固定 12 片段上限。
但 broad search 每公司每次最多索引最新 12 个 filing 正文；更多历史正文需目录发现后指定 accession 读取/检索。
单次片段 limit 1..20；legacy retriever 则仍使用总 limit 默认 12，按公司分额、按 filing 轮询。

## 公共网页

`web.py`：实验性 Bing RSS 搜索，摘要仅线索；read_web 获取原文后登记 URL、正文哈希、抓取时间及段落摘录。
公共读取验证 HTTPS、DNS/IP、重定向并固定连接地址，拒绝内网/本机地址，限制字节与总时间。
搜索质量、403、JS 动态页、付费墙与 PDF 都会限制研究。网页内容永远是资料，不是可执行指令。
公共读取总时限 45 秒、最多四轮含重定向请求，仅允许公共 HTTPS 443 且 URL 不带凭据；压缩响应当前拒绝。
公开行业背景不限 SEC，但结构化可比财务仍主要限支持的发行人。FTS 命中不等于因果结论成立。
