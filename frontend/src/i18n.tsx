import { createContext, useContext, useState, type ReactNode } from 'react';

export type Language = 'zh' | 'en';
export const english: Record<string,string> = {
  '读取 SEC 财报':'Read SEC filings','检索财报证据':'Search filing evidence','核验财务数据':'Verify financial data','组织研究结论':'Compose findings',
  '生成财务 XLSX':'Generate financial XLSX','生成核验 XLSX':'Generate verified XLSX','列出会话文件':'List session files','读取会话文件':'Read session file','写入工作文件':'Write working file','会话文件操作':'Session file operations',
  '查找财报目录':'Find filings','主动检索财报':'Search filings','读取财报原文':'Read original filing','查询并核验财务数据':'Fetch and verify financial data','浏览财务指标':'Browse financial concepts','检查来源证据':'Inspect evidence','更新研究计划':'Update research plan','检查执行环境':'Check execution capabilities','运行 Python':'Run Python','运行 Shell':'Run Shell','发布交付物':'Publish artifact','核对来源并交付研报':'Verify and publish report','发现最新完整财年':'Discover latest complete fiscal years','发现并确认公司':'Resolve companies','搜索公开资料':'Search public sources','读取网页证据':'Read web evidence','确定研究样本':'Set research sample',
  '营收':'Revenue','净利润':'Net income','营业利润':'Operating income','已完成':'Complete','未完成':'Incomplete','失败':'Failed','证据不足':'Insufficient evidence','已核验':'Verified','缺失':'Missing','不一致':'Mismatch',
  '复制':'Copy','编辑并重新生成':'Edit and regenerate','财报研究助手':'Financial Research Assistant','研究中':'Researching','研究计划：':'Research plan: ',
  '正在准备研究资料':'Preparing research material','回答生成中，最终引用尚待核验':'Generating answer; final citations are pending verification','本轮未完成，可重新生成':'This turn is incomplete. You can retry.',
  '财务工作簿 · 预览及下载 XLSX':'Financial workbook · Preview and download XLSX','研究报告 · 点击在工作区查看':'Research report · Open in workspace','复制回答':'Copy answer','重新生成本轮及之后的消息':'Regenerate this turn and subsequent messages',
  '✓ 已通过独立核验':'✓ Independently verified','部分数据未通过核验':'Some data failed verification','公司':'Company','指标':'Metric','财年':'Fiscal year','金额':'Amount','来源':'Sources','营收对比':'Revenue comparison','仅展示已核验数据 · 百万美元':'Verified data only · USD millions',
  '严格范围模式需要公司和财年；可关闭严格范围直接研究行业。':'Strict scope requires companies and fiscal years. Disable it to research an industry directly.',
  '新对话':'New conversation','已停止生成，当前内容尚未最终核验':'Generation stopped. Current content has not been finally verified.',
  '重新生成会替换本轮及之后的消息，继续吗？':'Regeneration replaces this turn and subsequent messages. Continue?',
  '编辑消息（将替换本轮及之后的消息）':'Edit message (replaces this turn and subsequent messages)',
  '快捷对比需选择公司和财年；也可直接在对话中要求 Agent 按研究样本生成 XLSX。':'Quick comparison requires companies and fiscal years. Alternatively, ask the agent to generate XLSX for its research sample.',
  '财报研究':'Financial Research','收起侧栏':'Collapse sidebar','搜索对话':'Search conversations','最近的对话':'Recent conversations','重命名':'Rename','会话名称':'Conversation title','删除会话':'Delete conversation','删除此会话及其消息、产物？':'Delete this conversation, its messages and artifacts?','本地研究空间':'Local research workspace','切换主题':'Toggle theme','展开侧栏':'Expand sidebar','SEC · 可溯源':'SEC · Source-backed','产物':'Artifacts',
  '关注公司（可选）':'Companies (optional)','期间由 Agent 判断':'Agent determines periods','正在生成并核验…':'Generating and verifying…','生成对比表':'Generate comparison','当前研究样本（非全行业）：':'Research sample (not the whole industry): ',
  '股票代码或公司名称，例如 AAOI':'Ticker or company name, e.g. AAOI','搜索中…':'Searching…','搜索公司':'Search companies','仅限所选公司及财年':'Restrict to selected companies and fiscal years','完成':'Done',
  '让每一项结论都有依据':'Evidence for every conclusion','今天想研究哪家公司？':'What would you like to research?','阅读财报、比较趋势、核验数据。':'Read filings, compare trends, verify data.','结论附原文引用，报告和表格留在工作区。':'Cited findings, with reports and spreadsheets in your workspace.',
  '分析这家公司近三年财报':'Analyze this company’s filings for the latest three years','比较所选公司的收入和盈利能力':'Compare revenue and profitability of the selected companies','梳理主要业务风险及变化':'Review key business risks and how they changed',
  '回到最新消息':'Scroll to latest message','向财报研究助手提问…':'Ask the financial research assistant…','可直接研究行业或公司，无需预选':'Research an industry or company directly; no preselection needed','停止生成':'Stop generation','发送消息':'Send message','依据 SEC 公开财报生成 · 点击引用核对原文 · Enter 发送，Shift + Enter 换行':'Based on public SEC filings · Click citations to verify · Enter to send, Shift + Enter for a new line',
  '来源核验':'Verify source','研究产物':'Research artifacts','展开工作区':'Expand workspace','关闭工作区':'Close workspace','正在读取原文…':'Loading original source…','← 返回产物':'← Back to artifacts','XBRL 财务事实':'XBRL financial fact','公开网页证据':'Public web evidence','SEC 原文':'Original SEC text','快照 SHA-256':'Snapshot SHA-256','文件编号':'Accession number','定位':'Locator',' 至 ':' to ','获取时间：':'Retrieved at: ','打开原始来源':'Open original source',
  '研究产物将显示在这里':'Research artifacts appear here','可让 Agent 生成 XLSX 或发布研究报告；普通回答不生成产物。':'Ask the agent to generate XLSX or publish a research report. Ordinary answers are not artifacts.','下载 XLSX':'Download XLSX','下载文件':'Download file','复制产物数据':'Copy artifact data','预览':'Preview','图表':'Chart','数据':'Data','来源引用规则已检查 · 金额与语义仍需人工复核':'Citation rules checked · Amounts and meaning still need human review','模型生成文件 · 未经财务数值独立核验':'Model-generated file · Financial values not independently verified',' 字节':' bytes',
  '等待确认':'Awaiting approval','已响应':'Responded','执行中':'Running','等待':'Pending','已拒绝':'Denied','参数':'Input','结果':'Output','复制代码':'Copy code','复制失败，请手动选择文本复制':'Copy failed. Select and copy the text manually.',
  '连接中断，回答尚未完成':'Connection interrupted before the answer was complete',
};

export function preferredLanguage(): Language { return localStorage.getItem('language') === 'en' ? 'en' : 'zh'; }
export function translate(text: string, language: Language = preferredLanguage()): string {
  if (language === 'zh') return text;
  return english[text] ?? text;
}
const LanguageContext = createContext({language: 'zh' as Language, setLanguage: (_: Language) => {}, t: (text: string) => text});
export function LanguageProvider({children}: {children: ReactNode}) {
  const [language, update] = useState<Language>(preferredLanguage);
  const setLanguage = (value: Language) => {localStorage.setItem('language', value); update(value);};
  return <LanguageContext.Provider value={{language, setLanguage, t: text => translate(text, language)}}>{children}</LanguageContext.Provider>;
}
export const useI18n = () => useContext(LanguageContext);
