import {Platform} from 'react-native';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import Constants from 'expo-constants';
Notifications.setNotificationHandler({handleNotification:async()=>({shouldShowBanner:true,shouldShowList:true,shouldPlaySound:true,shouldSetBadge:false})});
export async function registerPush(send:(token:string)=>Promise<void>){
  if(!Device.isDevice)throw new Error('Enable notifications on an installed app on your phone.');
  const projectId=Constants.expoConfig?.extra?.eas?.projectId||Constants.easConfig?.projectId;
  if(!projectId)throw new Error('Phone notifications are not connected for this build yet. Your practice administrator must finish setup.');
  if(Platform.OS==='android')await Notifications.setNotificationChannelAsync('appointments',{name:'Appointment updates',importance:Notifications.AndroidImportance.HIGH});
  let permission=await Notifications.getPermissionsAsync();
  if(permission.status!=='granted')permission=await Notifications.requestPermissionsAsync();
  if(permission.status!=='granted')throw new Error('Notifications are disabled. You can allow them in your phone settings.');
  const token=await Notifications.getExpoPushTokenAsync({projectId});await send(token.data);
}
