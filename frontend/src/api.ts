import {preferredLanguage, translate} from './i18n';
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { 'Content-Type':'application/json',...init?.headers } });
  if (!response.ok) {
    const data = await response.json().catch(()=>({}));
    throw new Error(typeof data.detail === 'string' ? data.detail : `${preferredLanguage()==='en'?'Request failed':'请求失败'} (${response.status})`);
  }
  return response.status === 204 ? undefined as T : response.json();
}
export async function stream(path: string, body: unknown, signal: AbortSignal, callback: (event: string,data: any)=>void) {
  const response = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json',Accept:'text/event-stream'},body:JSON.stringify(body),signal});
  if (!response.ok || !response.body) {
    const data=await response.json().catch(()=>({}));throw new Error(data.detail || `${preferredLanguage()==='en'?'Connection failed':'连接失败'} (${response.status})`);
  }
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',terminal=false;
  try {
    while (true) {
      const {value,done}=await reader.read();buffer+=decoder.decode(value,{stream:!done}).replace(/\r\n/g,'\n');
      let end=buffer.indexOf('\n\n');
      while(end>=0) {
        const lines=buffer.slice(0,end).split('\n');buffer=buffer.slice(end+2);
        const event=lines.find(l=>l.startsWith('event:'))?.slice(6).trim();
        const data=lines.filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trim()).join('\n');
        if(event&&data){callback(event,JSON.parse(data));if(event==='done')terminal=true;}
        end=buffer.indexOf('\n\n');
      }
      if(done)break;
    }
    if(!terminal)throw new Error(translate('连接中断，回答尚未完成'));
  }finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
}
