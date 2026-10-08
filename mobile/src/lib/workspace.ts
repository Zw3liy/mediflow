import type {Workspace} from './types';
export function fixedWorkspace():Workspace|null{
  const value=process.env.EXPO_PUBLIC_APP_WORKSPACE;
  return value==='doctor'||value==='patient'||value==='reception'?value:null;
}
