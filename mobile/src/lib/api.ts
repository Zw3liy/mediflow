import type {Session} from './types';
export class ApiError extends Error {constructor(message:string,public status:number){super(message);}}
export function normalizeServer(value:string){
  const url=new URL(value.trim());
  if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash||!['','/'].includes(url.pathname))throw new Error('Enter the HTTPS practice address provided by your administrator.');
  return url.origin;
}
function errorMessage(data:unknown):string{
  if(typeof data==='string')return data;
  if(Array.isArray(data))return data.map(errorMessage).join('\n');
  if(data&&typeof data==='object')return Object.entries(data).map(([key,value])=>`${key==='detail'?'':key+': '}${errorMessage(value)}`).join('\n');
  return 'Unable to complete this request.';
}
export async function request<T>(baseUrl:string,path:string,token?:string,body?:unknown,method?:string):Promise<T>{
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),path.startsWith('document-scans/')?70000:20000);
  try{
    const response=await fetch(`${baseUrl}/api/mobile/${path}`,{method:method??(body===undefined?'GET':'POST'),
      headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});
    const data=await response.json().catch(()=>({detail:'The practice server is unavailable. Try again shortly.'}));
    if(!response.ok)throw new ApiError(errorMessage(data),response.status);
    return data as T;
  }catch(error){if(error instanceof ApiError)throw error;throw new Error('Cannot reach your practice. Check your connection and try again.');}
  finally{clearTimeout(timeout);}
}
export function authenticated<T>(session:Session,path:string,body?:unknown,method?:string){return request<T>(session.baseUrl,path,session.token,body,method);}
