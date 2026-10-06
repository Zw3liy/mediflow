import React,{createContext,useContext,useEffect,useState,useCallback} from 'react';
import * as SecureStore from 'expo-secure-store';
import {authenticated,ApiError,normalizeServer,request} from './api';
import type {Dashboard,Session,SessionInfo,Workspace} from './types';
const KEY='mediflow.native.session.v1';
type Context={session:Session|null;ready:boolean;signIn:(url:string,workspace:Workspace,username:string,password:string)=>Promise<void>;signOut:()=>Promise<void>;call:<T>(path:string,body?:unknown,method?:string)=>Promise<T>};
const SessionContext=createContext<Context|null>(null);
export function SessionProvider({children}:{children:React.ReactNode}){
  const [session,setSession]=useState<Session|null>(null);const [ready,setReady]=useState(false);
  useEffect(()=>{let alive=true;SecureStore.getItemAsync(KEY).then(raw=>{if(!alive)return;if(raw){try{const saved=JSON.parse(raw) as Session;if(saved.token&&saved.baseUrl&&Date.parse(saved.session.expires_at)>Date.now())setSession(saved);else void SecureStore.deleteItemAsync(KEY);}catch{void SecureStore.deleteItemAsync(KEY);}}}).catch(()=>{}).finally(()=>{if(alive)setReady(true);});return()=>{alive=false;};},[]);
  const clear=useCallback(async()=>{setSession(null);await SecureStore.deleteItemAsync(KEY);},[]);
  const signIn=async(url:string,workspace:Workspace,username:string,password:string)=>{
    const baseUrl=normalizeServer(url);const result=await request<{token:string;session:SessionInfo}>(baseUrl,'login/',undefined,{workspace,username:username.trim(),password});
    const saved={...result,baseUrl};await SecureStore.setItemAsync(KEY,JSON.stringify(saved),{keychainAccessible:SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY});setSession(saved);
  };
  const signOut=async()=>{if(session){try{await authenticated(session,'logout/',{});}catch(error){if(!(error instanceof ApiError&&error.status===401))throw error;}}await clear();};
  const call=useCallback(async<T,>(path:string,body?:unknown,method?:string):Promise<T>=>{
    if(!session)throw new Error('Sign in to continue.');
    try{return await authenticated<T>(session,path,body,method);}catch(error){if(error instanceof ApiError&&error.status===401)await clear();throw error;}
  },[session,clear]);
  useEffect(()=>{if(session)void authenticated<Dashboard>(session,'dashboard/').catch(error=>{if(error instanceof ApiError&&error.status===401)void clear();});},[session,clear]);
  return <SessionContext.Provider value={{session,ready,signIn,signOut,call}}>{children}</SessionContext.Provider>;
}
export function useSession(){const context=useContext(SessionContext);if(!context)throw new Error('Session provider missing');return context;}
