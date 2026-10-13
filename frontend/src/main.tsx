import { createRoot } from 'react-dom/client';
import { useState, useEffect, useRef, createContext, useContext } from 'react';
import { AssistantRuntimeProvider, useExternalStoreRuntime, ThreadPrimitive, MessagePrimitive,
  ComposerPrimitive, useAuiState, type ThreadMessageLike, type AppendMessage } from '@assistant-ui/react';
import { Plus, Search, PanelLeft, Sun, Moon, ArrowUp, Square, Copy, RefreshCw, Pencil,
  Trash2, FileText, Table2, Download, X, ArrowDown, ChartNoAxesCombined, ExternalLink,
  ChevronDown, Check, Maximize2, Minimize2, Sparkles, FolderOpen } from 'lucide-react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { Tool, ToolHeader, ToolContent } from './components/ai-elements/tool';
import { Artifact, ArtifactHeader, ArtifactTitle, ArtifactActions, ArtifactContent } from './components/ai-elements/artifact';
import { api, stream } from './api';
import { messageId, copyText } from './lib/browser';
import type { Thread, Message, Scope, ThreadSummary, Company, Answer, ArtifactData, FinancialTable, TextDocument } from './types';
import './styles.css';
import { LanguageProvider, useI18n } from './i18n';

const defaultScope: Scope = {companies:[],fiscal_years:[],forms:['10-K','10-Q'],restatement_policy:'latest_restated',strict:false};
const names: Record<string,string> = {ingestion:'读取 SEC 财报',retrieval:'检索财报证据',verification:'核验财务数据',generation:'组织研究结论',
  workbook:'生成财务 XLSX',
  generate_workbook:'生成核验 XLSX',list_files:'列出会话文件',read_file:'读取会话文件',write_file:'写入工作文件',
  files:'会话文件操作',
  list_filings:'查找财报目录',search_filings:'主动检索财报',read_filing:'读取财报原文',
  get_financial_data:'查询并核验财务数据',list_financial_concepts:'浏览财务指标',
  inspect_evidence:'检查来源证据',update_plan:'更新研究计划',execution_capabilities:'检查执行环境',
  run_python:'运行 Python',run_shell:'运行 Shell',publish_artifact:'发布交付物',
  publish_report:'核对来源并交付研报',
  discover_financial_periods:'发现最新完整财年',
  resolve_companies:'发现并确认公司',search_web:'搜索公开资料',read_web:'读取网页证据',set_research_sample:'确定研究样本',
  revenue:'营收',net_income:'净利润',operating_income:'营业利润',complete:'已完成',incomplete:'未完成',error:'失败',refused:'证据不足',verified:'已核验',missing:'缺失',mismatch:'不一致'};
const WorkspaceContext = createContext<{
  messages: Message[]; artifacts: ArtifactData[]; running: boolean;
  showSource:(id:string)=>void; showArtifact:(a:ArtifactData)=>void;
  resend:(m:Message)=>void; edit:(m:Message)=>void;
}>({messages:[],artifacts:[],running:false,showSource:()=>{},showArtifact:()=>{},resend:()=>{},edit:()=>{}});

function RichText({text}:{text:string}) {
  const {showSource}=useContext(WorkspaceContext);
  return <Markdown remarkPlugins={[remarkGfm]} rehypePlugins={[[rehypeHighlight,{detect:false}]]}
    components={{a:({href,children})=>href?.startsWith('#source/')
      ? <button className="citation" onClick={()=>showSource(href.slice(8))}>{children}</button>
      : <a href={href} target="_blank" rel="noreferrer">{children}</a>}}>{text}</Markdown>;
}
function AnswerBody({answer}:{answer:Answer}) {
  const ids=[...new Set(answer.claims.flatMap(c=>c.citation_ids))];
  return <div className="prose-answer">{answer.message&&<RichText text={answer.message}/>}{answer.claims.map((claim,index)=><RichText key={index}
    text={claim.text+' '+claim.citation_ids.map(id=>`[\\[${ids.indexOf(id)+1}\\]](#source/${id})`).join(' ')}/>)}
    {answer.caveats.map((c,i)=><p className="notice" key={i}>{c}</p>)}</div>;
}
function ResearchMessage() {
  const {t,language}=useI18n();
  const id=useAuiState(s=>s.message.id);
  const ctx=useContext(WorkspaceContext);
  const message=ctx.messages.find(m=>m.id===id);
  const [copied,setCopied]=useState(false);
  if(!message)return null;
  const keys=[...new Set(message.events.filter(e=>e.event==='status').map(e=>e.data.tool_call_id||e.data.phase))];
  const stages=keys.map(key=>{const items=message.events.filter(e=>e.event==='status'&&(e.data.tool_call_id||e.data.phase)===key);return {key,phase:items[0].data.phase,items};});
  const lastSource=message.events.findLast(e=>e.event==='sources');
  const copy=async()=>{await copyText(message.content);setCopied(true);setTimeout(()=>setCopied(false),1500);};
  return <MessagePrimitive.Root className={'message '+message.role}>
    {message.role==='user'?<>
      <div className="user-bubble">{message.content}</div>
      <div className="message-actions"><button title={t("复制")} onClick={copy}>{copied?<Check size={15}/>:<Copy size={15}/>}</button><button title={t("编辑并重新生成")} disabled={ctx.running} onClick={()=>ctx.edit(message)}><Pencil size={15}/></button></div>
    </>:<>
      <div className="assistant-label"><span className="assistant-icon"><Sparkles size={15}/></span>{t('财报研究助手')}
        <span className={'message-status '+message.status}>{message.status==='running'?t("研究中"):t(names[message.status]||message.status)||message.status}</span></div>
      <div className="tool-stack">{stages.map(({phase,items})=>{
        const last=items[items.length-1].data;
        const state=last.state==='complete'?'output-available':last.state==='warning'?'output-error':message.status==='running'?'input-available':'output-error';
        return <Tool key={items[0].data.tool_call_id||phase}><ToolHeader type="dynamic-tool" toolName={phase} title={t(names[phase]||phase)||phase} state={state}/>
          <ToolContent><div className="tool-log">{items.map((item,i)=><p key={i}>{item.data.message}</p>)}</div>
            {last.detail&&<pre>{JSON.stringify(last.detail,null,2)}</pre>}</ToolContent></Tool>;
      })}</div>
      {message.events.findLast(e=>e.event==='plan')&&<div className="notice">{t('研究计划：')}{message.events.findLast(e=>e.event==='plan')!.data.steps.join(' → ')}</div>}
      {lastSource&&<div className="source-count">{language==='en'?`${lastSource.data.count} sources · ${lastSource.data.xbrl_count} financial facts · ${lastSource.data.narrative_count} passages`:`${lastSource.data.count} 条来源 · ${lastSource.data.xbrl_count} 条财务数据 · ${lastSource.data.narrative_count} 条原文`}</div>}
      {message.answer?<AnswerBody answer={message.answer}/>:message.content?<RichText text={message.content}/>:message.status==='running'?<div className="thinking"><span/><span/><span/>{t("正在准备研究资料")}</div>:null}
      {message.status==='running'&&<div className="stream-indicator">{t("回答生成中，最终引用尚待核验")}</div>}
      {['error','incomplete','refused'].includes(message.status)&&<div className="notice">{t(names[message.status]||message.status)} · {message.answer?.status_reason||t("本轮未完成，可重新生成")}</div>}
      {ctx.artifacts.filter(a=>(a.file?.origin_message_id||a.message_id)===message.id).map(a=><button className="artifact-card" key={a.id} onClick={()=>ctx.showArtifact(a)}>
        {a.kind==='table'?<Table2 size={22}/>:<FileText size={22}/>}<span><strong>{a.title}</strong><small>{a.kind==='table'?t("财务工作簿 · 预览及下载 XLSX"):t("研究报告 · 点击在工作区查看")}</small></span><ExternalLink size={15}/></button>)}
      {message.status!=='running'&&<div className="message-actions"><button title={t("复制回答")} onClick={copy}>{copied?<Check size={15}/>:<Copy size={15}/>}</button>
        <button title={t("重新生成本轮及之后的消息")} disabled={ctx.running} onClick={()=>ctx.resend(message)}><RefreshCw size={15}/></button></div>}
    </>}
  </MessagePrimitive.Root>;
}
function TablePreview({table}:{table:FinancialTable}) {
  const {t,language}=useI18n();
  const {showSource}=useContext(WorkspaceContext);
  return <><div className="table-state">{table.verified?t("✓ 已通过独立核验"):t("部分数据未通过核验")}</div><div className="table-scroll"><table><thead><tr><th>{t("公司")}</th><th>{t("指标")}</th><th>{t("财年")}</th><th>{t("金额")}</th><th>{t("来源")}</th></tr></thead>
    <tbody>{table.rows.map((r,i)=><tr key={i}><td>{r.company.ticker}</td><td>{t(names[r.metric]||r.metric)||r.metric}</td><td>{r.period}</td><td>{r.cell.display_value} {r.cell.unit}</td><td>{r.cell.source_citation_ids.map((id,j)=><button className="citation" key={id} onClick={()=>showSource(id)}>[{j+1}]</button>)}</td></tr>)}</tbody></table></div>
    {table.warnings.map((w,i)=><p className="notice" key={i}>{w}</p>)}</>;
}
function FinancialChart({table}:{table:FinancialTable}) {
  const {t,language}=useI18n();
  const rows=table.rows.filter(r=>r.metric==='revenue'&&r.cell.value!==null&&r.cell.verification.status==='verified');
  const max=Math.max(...rows.map(r=>Math.abs(Number(r.cell.value))),1);
  return <div className="chart"><h3>{t("营收对比")}</h3><p>{t("仅展示已核验数据 · 百万美元")}</p>{rows.map((r,i)=><div className="bar-row" key={i}>
    <span>{r.company.ticker}<small>{r.period}</small></span><div><i style={{width:`${Math.abs(Number(r.cell.value))/max*100}%`}}/></div><strong>{(Number(r.cell.value)/1e6).toFixed(2)}</strong></div>)}</div>;
}
function downloadText(text:string,name:string) {const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type:'text/markdown;charset=utf-8'}));a.download=name;a.click();URL.revokeObjectURL(a.href);}

function App() {
  const {t,language,setLanguage}=useI18n();
  const [threads,setThreads]=useState<ThreadSummary[]>([]),[thread,setThread]=useState<Thread|null>(null);
  const [scope,setScope]=useState<Scope>(defaultScope),[running,setRunning]=useState(false),[tableBusy,setTableBusy]=useState(false);
  const [error,setError]=useState(''),[query,setQuery]=useState(''),[results,setResults]=useState<Company[]>([]),[searching,setSearching]=useState(false);
  const [scopeOpen,setScopeOpen]=useState(false),[sidebar,setSidebar]=useState(window.innerWidth>640),[filter,setFilter]=useState('');
  const [dark,setDark]=useState(localStorage.getItem('theme')==='dark');
  const [selected,setSelected]=useState<ArtifactData|null>(null),[source,setSource]=useState<any>(null),[sourceLoading,setSourceLoading]=useState(false);
  const [panel,setPanel]=useState(false),[expanded,setExpanded]=useState(false),[tab,setTab]=useState('preview');
  const controller=useRef<AbortController|null>(null);
  const refresh=async()=>setThreads(await api<ThreadSummary[]>('/api/threads'));
  const load=async(id:string)=>{const t=await api<Thread>('/api/threads/'+id);setThread(t);setScope({...t.scope||defaultScope,language});setSelected(t.artifacts.at(-1)||null);setSource(null);localStorage.setItem('thread',id);};
  const create=async()=>{const t=await api<Thread>('/api/threads',{method:'POST'});setThread(t);setScope({...defaultScope,language});setSelected(null);setSource(null);setPanel(false);localStorage.setItem('thread',t.id);await refresh();};
  useEffect(()=>{(async()=>{try{const list=await api<ThreadSummary[]>('/api/threads');setThreads(list);const id=localStorage.getItem('thread');if(list.length)await load(list.find(t=>t.id===id)?.id||list[0].id);else await create();}catch(e){setError(String(e));}})();},[]);
  useEffect(()=>{document.documentElement.dataset.theme=dark?'dark':'light';localStorage.setItem('theme',dark?'dark':'light');},[dark]);
  useEffect(()=>{document.documentElement.lang=language;document.title=t('财报研究助手');},[language]);
  const updateMessage=(id:string,fn:(m:Message)=>Message)=>setThread(t=>t?{...t,messages:t.messages.map(m=>m.id===id?fn(m):m)}:t);
  const send=async(question:string,replace?:string)=>{
    if(!thread||running||tableBusy)return;
    if(scope.strict&&(!scope.companies.length||!scope.fiscal_years.length)){setError(t("严格范围模式需要公司和财年；可关闭严格范围直接研究行业。"));return;}
    const threadId=thread.id;const cut=replace?thread.messages.findIndex(m=>m.id===replace):-1;
    const userId=messageId(),pendingId=messageId();let assistantId=pendingId;
    const kept=cut>=0?thread.messages.slice(0,cut):thread.messages;
    setThread(t=>t?{...t,messages:[...kept,{id:userId,role:'user',content:question,events:[],status:'complete'},{id:pendingId,role:'assistant',content:'',events:[],status:'running'}],
      artifacts:t.artifacts}:t);
    setError('');setRunning(true);controller.current=new AbortController();let latest:Answer|undefined;let finalStatus='incomplete';
    try{
      await stream(`/api/threads/${threadId}/messages/stream`,{question,scope:{...scope,language},replace_from:replace},controller.current.signal,(event,data)=>{
        if(event==='message.created'){
          assistantId=data.assistant_id;setThread(t=>t?{...t,title:t.title==='新对话'?question.slice(0,40):t.title,messages:t.messages.map(m=>m.id===pendingId?{...m,id:assistantId}:m.id===userId?{...m,id:data.user_id}:m)}:t);
        }else if(event==='answer.snapshot'){
          if(data.status_reason==='validation_retry'||(!data.claims.length&&data.status_reason==='streaming'))return;
          latest=data;updateMessage(assistantId,m=>({...m,answer:data,content:[data.message,...data.claims.map((c:any)=>c.text)].filter(Boolean).join('\n\n')}));
        }else if(event==='artifact'){setThread(t=>t?{...t,artifacts:[...t.artifacts,data]}:t);setSelected(data);}
        else if(event==='done'){finalStatus=data.status;updateMessage(assistantId,m=>({...m,status:data.status}));}
        else if(event==='sample'){setThread(t=>t?{...t,research_sample:data}:t);updateMessage(assistantId,m=>({...m,events:[...m.events,{event,data}]}));}
        else if(['status','sources','error','plan'].includes(event)){updateMessage(assistantId,m=>({...m,events:[...m.events,{event,data}]}));if(event==='error')setError(data.message);}
      });
    }catch(e){const message=e instanceof Error?e.name==='AbortError'?t("已停止生成，当前内容尚未最终核验"):e.message:String(e);setError(message);updateMessage(assistantId,m=>({...m,status:'incomplete',answer:latest?{...latest,status:'incomplete',status_reason:message}:undefined}));}
    finally{controller.current=null;setRunning(false);updateMessage(assistantId,m=>m.status==='running'?{...m,status:finalStatus}:m);await refresh().catch(()=>{});}
  };
  const resend=(message:Message)=>{const i=thread?.messages.findIndex(m=>m.id===message.id)??-1;const user=thread?.messages.slice(0,i).findLast(m=>m.role==='user');if(user){if(i<(thread?.messages.length||0)-1&&!confirm(t("重新生成会替换本轮及之后的消息，继续吗？")))return;void send(user.content,user.id);}};
  const edit=(message:Message)=>{const text=prompt(t("编辑消息（将替换本轮及之后的消息）"),message.content);if(text?.trim())void send(text.trim(),message.id);};
  const convertMessage=(m:Message):ThreadMessageLike=>({id:m.id,role:m.role,content:[{type:'text',text:m.content}],
    ...(m.role==='assistant'?{status:m.status==='running'?{type:'running'}:m.status==='complete'?{type:'complete',reason:'stop'}:{type:'incomplete',reason:'error'}}:{})});
  const runtime=useExternalStoreRuntime({messages:thread?.messages||[],isRunning:running,convertMessage,
    onNew:async(m:AppendMessage)=>{await send(m.content.filter(c=>c.type==='text').map(c=>c.text).join('\n'));},
    onCancel:async()=>{controller.current?.abort();},isSendDisabled:tableBusy});
  const showSource=async(id:string)=>{setPanel(true);setSource(null);setSourceLoading(true);try{setSource(await api('/api/sources/'+id));}catch(e){setError(String(e));}finally{setSourceLoading(false);}};
  const showArtifact=(a:ArtifactData)=>{setSelected(a);setSource(null);setPanel(true);setTab('preview');};
  const compare=async()=>{if(!thread||!scope.companies.length||!scope.fiscal_years.length){setScopeOpen(true);setError(t("快捷对比需选择公司和财年；也可直接在对话中要求 Agent 按研究样本生成 XLSX。"));return;}setTableBusy(true);setError('');
    try{const a=await api<ArtifactData>(`/api/threads/${thread.id}/artifacts/table`,{method:'POST',body:JSON.stringify({scope:{...scope,language},metrics:['revenue','net_income','operating_income'],periods:scope.fiscal_years.map(y=>`${y}-FY`)})});setThread(t=>t?{...t,artifacts:[...t.artifacts,a]}:t);showArtifact(a);}catch(e){setError(String(e));}finally{setTableBusy(false);}};
  const search=async()=>{if(!query.trim())return;setSearching(true);try{setResults(await api<Company[]>('/api/companies/search?q='+encodeURIComponent(query)));}catch(e){setError(String(e));}finally{setSearching(false);}};
  const busy=running||tableBusy;
  return <AssistantRuntimeProvider runtime={runtime}><WorkspaceContext.Provider value={{messages:thread?.messages||[],artifacts:thread?.artifacts||[],running,showSource,showArtifact,resend,edit}}>
  <div className={'app '+(sidebar?'':'sidebar-hidden')+(panel?' panel-visible':'')+(expanded?' panel-expanded':'')}>
    <aside className="sidebar"><div className="brand"><span><ChartNoAxesCombined size={21}/></span><strong>{t("财报研究")}</strong><button onClick={()=>setSidebar(false)} title={t("收起侧栏")}><PanelLeft size={18}/></button></div>
      <button className="new-chat" disabled={busy} onClick={()=>void create().catch(e=>setError(String(e)))}><Plus size={18}/>{t("新对话")}</button>
      <div className="history-search"><Search size={14}/><input placeholder={t("搜索对话")} value={filter} onChange={e=>setFilter(e.target.value)}/></div>
      <p className="section-label">{t("最近的对话")}</p><nav>{threads.filter(item=>item.title.includes(filter)).map(item=><div key={item.id} className={'thread-item '+(thread?.id===item.id?'selected':'')}>
        <button className="thread-title" disabled={busy} onClick={()=>void load(item.id).catch(e=>setError(String(e)))}><span>{t(item.title)}</span></button>
        <button title={t("重命名")} disabled={busy} onClick={async()=>{const title=prompt(t("会话名称"),item.title);if(title){await api('/api/threads/'+item.id,{method:'PATCH',body:JSON.stringify({title})});await refresh();if(thread?.id===item.id)setThread({...thread,title});}}}><Pencil size={13}/></button>
        <button title={t("删除会话")} disabled={busy} onClick={async()=>{if(!confirm(t("删除此会话及其消息、产物？")))return;await api('/api/threads/'+item.id,{method:'DELETE'});if(thread?.id===item.id)await create();else await refresh();}}><Trash2 size={13}/></button>
      </div>)}</nav><div className="sidebar-bottom"><span className="online-dot"/>{t("本地研究空间")}<button title={t("切换主题")} onClick={()=>setDark(!dark)}>{dark?<Sun size={18}/>:<Moon size={18}/>}</button></div>
    </aside>
    <main className="chat-main"><header className="topbar"><div>{!sidebar&&<button title={t("展开侧栏")} onClick={()=>setSidebar(true)}><PanelLeft size={19}/></button>}<strong>{t(thread?.title||'财报研究助手')}</strong><span className="top-badge">{t("SEC · 可溯源")}</span></div>
      <button className="language-toggle" disabled={busy} aria-label="Switch language" onClick={()=>{const next=language==='zh'?'en':'zh';setLanguage(next);setScope({...scope,language:next});setError('');}}>{language==='zh'?'English':'中文'}</button><button className="workspace-button" onClick={()=>{setPanel(!panel);setSource(null);}}><FolderOpen size={17}/>{t("产物")}<span>{thread?.artifacts.length||0}</span></button></header>
      <div className="scope-bar"><button disabled={busy} onClick={()=>setScopeOpen(!scopeOpen)}><span className="scope-dot"/>{scope.companies.length?scope.companies.map(c=>c.ticker).join(' / '):t("关注公司（可选）")}<ChevronDown size={14}/></button>
        <span>{scope.fiscal_years.length?scope.fiscal_years.join(' · '):t("期间由 Agent 判断")}</span><button className="compare-button" disabled={busy} onClick={()=>void compare()}><Table2 size={15}/>{tableBusy?t("正在生成并核验…"):t("生成对比表")}</button></div>
      {thread?.research_sample&&<div className="notice">{t('当前研究样本（非全行业）：')}{thread.research_sample.members.map(m=><button key={m.company.cik} title={m.reason} onClick={()=>void showSource(m.citation_ids[0])}>{m.company.ticker} · {m.company.name} </button>)}</div>}
      {scopeOpen&&<section className="scope-editor"><div className="scope-search"><input placeholder={t("股票代码或公司名称，例如 AAOI")} value={query} disabled={busy} onChange={e=>setQuery(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')void search();}}/><button disabled={busy||searching} onClick={()=>void search()}>{searching?t("搜索中…"):t("搜索公司")}</button></div>
        <div className="company-results">{results.map(c=><button key={c.cik} disabled={busy} onClick={()=>{if(!scope.companies.some(x=>x.cik===c.cik)&&scope.companies.length<3)setScope({...scope,companies:[...scope.companies,c]});}}><strong>{c.ticker}</strong><span>{c.name}</span><Plus size={14}/></button>)}</div>
        <div className="scope-fields"><div className="company-chips">{scope.companies.map(c=><button key={c.cik} disabled={busy} onClick={()=>setScope({...scope,companies:scope.companies.filter(x=>x.cik!==c.cik)})}>{c.ticker}<X size={12}/></button>)}</div>
          <label>{t("财年")}<input defaultValue={scope.fiscal_years.join(',')} disabled={busy} onBlur={e=>setScope({...scope,fiscal_years:[...new Set(e.target.value.split(/[,，]/).map(Number).filter(y=>y>=1990&&y<=2100))].sort((a,b)=>b-a)})}/></label>
          {['10-K','10-Q'].map(form=><label key={form}><input type="checkbox" disabled={busy} checked={scope.forms.includes(form)} onChange={e=>setScope({...scope,forms:e.target.checked?[...scope.forms,form]:scope.forms.filter(f=>f!==form)})}/>{form}</label>)}
          <label><input type="checkbox" disabled={busy} checked={scope.strict||false} onChange={e=>setScope({...scope,strict:e.target.checked})}/>{t("仅限所选公司及财年")}</label>
          <button onClick={()=>setScopeOpen(false)}>{t("完成")}</button></div></section>}
      <ThreadPrimitive.Root className="thread-root"><ThreadPrimitive.Viewport className="conversation">
        <ThreadPrimitive.Empty><div className="welcome"><span className="welcome-icon"><ChartNoAxesCombined size={33}/></span><p className="welcome-kicker">{t("让每一项结论都有依据")}</p><h1>{t("今天想研究哪家公司？")}</h1><p>{t("阅读财报、比较趋势、核验数据。")}<br/>{t("结论附原文引用，报告和表格留在工作区。")}</p>
          <div className="suggestions">{[t("分析这家公司近三年财报"),t("比较所选公司的收入和盈利能力"),t("梳理主要业务风险及变化")].map(text=><button key={text} onClick={()=>runtime.thread.composer.setText(text)}><Sparkles size={16}/>{text}</button>)}</div></div></ThreadPrimitive.Empty>
        <div className="message-list"><ThreadPrimitive.Messages components={{UserMessage:ResearchMessage,AssistantMessage:ResearchMessage}}/></div>
        <ThreadPrimitive.ScrollToBottom className="scroll-bottom" title={t("回到最新消息")}><ArrowDown size={17}/></ThreadPrimitive.ScrollToBottom>
      </ThreadPrimitive.Viewport>
      <div className="composer-area">{error&&<div className="error-banner">{error}<button onClick={()=>setError('')}><X size={14}/></button></div>}
        <ComposerPrimitive.Root className="composer"><ComposerPrimitive.Input placeholder={t("向财报研究助手提问…")} className="composer-input" disabled={tableBusy}/>
          <div className="composer-footer"><span><span className="scope-dot"/>{scope.companies.length?(language==='en'?`Following ${scope.companies.length} companies · ${scope.strict?'Strict scope':'Expandable'}`:`关注 ${scope.companies.length} 家公司${scope.strict?' · 严格范围':' · 可拓展'}`):t("可直接研究行业或公司，无需预选")}</span>
            {running?<ComposerPrimitive.Cancel className="send-button stop-button" title={t("停止生成")}><Square size={16}/></ComposerPrimitive.Cancel>:<ComposerPrimitive.Send className="send-button" disabled={tableBusy} title={t("发送消息")}><ArrowUp size={19}/></ComposerPrimitive.Send>}</div>
        </ComposerPrimitive.Root><p className="composer-note">{t("依据 SEC 公开财报生成 · 点击引用核对原文 · Enter 发送，Shift + Enter 换行")}</p></div>
      </ThreadPrimitive.Root>
    </main>
    {panel&&<aside className="artifact-panel"><div className="panel-top"><strong>{source||sourceLoading?t("来源核验"):t("研究产物")}</strong><div><button title={t("展开工作区")} onClick={()=>setExpanded(!expanded)}>{expanded?<Minimize2 size={16}/>:<Maximize2 size={16}/>}</button><button title={t("关闭工作区")} onClick={()=>{setPanel(false);setExpanded(false);}}><X size={18}/></button></div></div>
      {sourceLoading?<div className="panel-empty">{t("正在读取原文…")}</div>:source?<section className="source-view"><button className="back-button" onClick={()=>setSource(null)}>{t("← 返回产物")}</button><span className="top-badge">{source.source.source_type==='xbrl'?t("XBRL 财务事实"):source.source.source_type==='web'?t("公开网页证据"):t("SEC 原文")}</span><h2>{source.source.title||`${source.source.ticker} · ${source.source.form}`}</h2><p className="source-meta">{source.source.source_type==='web'?t("快照 SHA-256"):t("文件编号")}<br/>{source.source.content_sha256||source.source.accession_no}</p><h3>{t("定位")}</h3><p>{source.locator.section||source.locator.concept||source.locator.operation}</p>
        {source.value&&<div className="source-value">{Number(source.value.amount).toLocaleString()} {source.value.unit}</div>}{source.locator.exact_quote&&<blockquote>{source.locator.exact_quote}</blockquote>}
        {source.locator.start&&<p>{source.locator.start}{t(' 至 ')}{source.locator.end}</p>}<p>{t('获取时间：')}{source.retrieved_at}</p><a href={source.source.sec_url} target="_blank" rel="noreferrer">{t("打开原始来源")} <ExternalLink size={14}/></a></section>:<>
        <div className="artifact-list">{thread?.artifacts.map(a=><button key={a.id} className={selected?.id===a.id?'active':''} onClick={()=>{setSelected(a);setTab('preview');}}>{a.kind==='table'?<Table2 size={15}/>:<FileText size={15}/>}<span>{a.file?.relative_path||a.title}</span></button>)}</div>
        {!selected?<div className="panel-empty"><FileText size={32}/><h3>{t("研究产物将显示在这里")}</h3><p>{t("可让 Agent 生成 XLSX 或发布研究报告；普通回答不生成产物。")}</p></div>:<Artifact className="artifact-view"><ArtifactHeader><ArtifactTitle>{selected.title}</ArtifactTitle><ArtifactActions>
          <a className="icon-button" title={selected.kind==='table'?t("下载 XLSX"):t("下载文件")} href={'/api/artifacts/'+selected.id+'/download'}><Download size={16}/></a>
          <button title={t("复制产物数据")} onClick={()=>void copyText(JSON.stringify(selected.data,null,2))}><Copy size={16}/></button></ArtifactActions></ArtifactHeader>
          <div className="artifact-tabs">{['preview',...(selected.kind==='table'?['chart']:[]),'data'].map(value=><button className={tab===value?'active':''} key={value} onClick={()=>setTab(value)}>{value==='preview'?t("预览"):value==='chart'?t("图表"):t("数据")}</button>)}</div>
          <ArtifactContent>{tab==='data'?<pre className="raw-data">{JSON.stringify(selected.data,null,2)}</pre>:selected.kind==='document'?<><p className="notice">{(selected.data as any).report?t("来源引用规则已检查 · 金额与语义仍需人工复核"):t("模型生成文件 · 未经财务数值独立核验")}</p>{(selected.data as any).report?<AnswerBody answer={(selected.data as any).answer}/>:<RichText text={(selected.data as TextDocument).text}/>}</>:selected.kind==='report'?<AnswerBody answer={selected.data as Answer}/>:tab==='chart'?<FinancialChart table={selected.data as FinancialTable}/>:<TablePreview table={selected.data as FinancialTable}/>}</ArtifactContent>
          <p className="artifact-scope">{selected.file?.relative_path} · {selected.file?.size_bytes}{t(' 字节')}<br/>{selected.scope.companies.map(c=>c.ticker).join(' / ')} · {selected.scope.fiscal_years.join(language==='en'?', ':'、')}</p></Artifact>}
      </>}
    </aside>}
  </div></WorkspaceContext.Provider></AssistantRuntimeProvider>;
}
createRoot(document.getElementById('root')!).render(<LanguageProvider><App/></LanguageProvider>);
