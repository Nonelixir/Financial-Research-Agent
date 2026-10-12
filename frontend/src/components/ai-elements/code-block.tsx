import { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import Markdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import { copyText } from '@/lib/browser';
import {useI18n} from '@/i18n';
export function CodeBlock({ code, language }: { code: string; language: string }) {
  const {t} = useI18n();
  const [copied,setCopied] = useState(false);
  return <div className="code-block"><div><span>{language}</span><button aria-label={t('复制代码')} onClick={async()=>{
    await copyText(code);setCopied(true);setTimeout(()=>setCopied(false),1500);
  }}>{copied?<Check size={14}/>:<Copy size={14}/>}</button></div>
  <Markdown rehypePlugins={[[rehypeHighlight,{detect:false}]]}>{'```'+language+'\n'+code+'\n```'}</Markdown></div>;
}
