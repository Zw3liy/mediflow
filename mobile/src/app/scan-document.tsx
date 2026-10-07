import {useCallback,useEffect,useState} from 'react';
import {Alert,Image,Switch,Text,View} from 'react-native';
import {Redirect,router} from 'expo-router';
import * as ImagePicker from 'expo-image-picker';
import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import {useSession} from '../lib/session';
import {ChoiceField} from '../components/choice';
import {Action,Card,ErrorText,Field,Screen,s} from '../components/ui';

type Details={file_number:string;given_name:string;family_name:string;date_of_birth:string|null;mobile:string;email:string;address:string};
type Patient=Details&{id:string;name:string;updated_at:string};
type Scan={id:string;title:string;extracted_text:string;reviewed_text:string;suggestions:Partial<Details>;reviewed_at:string|null;patient_id:string|null};
type Options={patients:Patient[];documents:Scan[];drafts:Scan[]};
const empty:Details={file_number:'',given_name:'',family_name:'',date_of_birth:null,mobile:'',email:'',address:''};
const labels:Record<keyof Details,string>={file_number:'Patient file number',given_name:'Given name',family_name:'Family name',date_of_birth:'Date of birth (YYYY-MM-DD)',mobile:'Mobile number',email:'Email',address:'Address'};

export default function ScanDocument(){
  const {session,call}=useSession();
  const [options,setOptions]=useState<Options>({patients:[],documents:[],drafts:[]});
  const [scan,setScan]=useState<Scan|null>(null);
  const [image,setImage]=useState('');const [encoded,setEncoded]=useState('');
  const [patientId,setPatientId]=useState('');const [details,setDetails]=useState<Details>({...empty});
  const [title,setTitle]=useState('Scanned document');const [text,setText]=useState('');
  const [confirmed,setConfirmed]=useState(false);const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const isStaff=!!session&&['owner','reception'].includes(session.session.role);
  const refresh=useCallback(async()=>{setOptions(await call<Options>('document-scans/'));},[call]);
  const acceptImage=useCallback((result:ImagePicker.ImagePickerResult)=>{
    if(result.canceled)return;
    const photo=result.assets[0];
    if(!photo.base64)throw new Error('The image could not be read. Please choose it again.');
    if(photo.base64.length>11184812)throw new Error('Choose a photo smaller than 8 MB.');
    setImage(`data:image/jpeg;base64,${photo.base64}`);setEncoded(photo.base64);setError('');
  },[]);
  useEffect(()=>{if(!isStaff)return;const timer=setTimeout(()=>{void refresh().catch(e=>setError((e as Error).message));},0);
    void ImagePicker.getPendingResultAsync().then(result=>{if(result&&'canceled' in result)acceptImage(result);}).catch(e=>setError((e as Error).message));
    return()=>clearTimeout(timer);
  },[isStaff,refresh,acceptImage]);
  if(!session)return <Redirect href="/"/>;
  if(!isStaff)return <Redirect href="/home"/>;
  const saved=!!scan?.reviewed_at;const baseline=options.patients.find(p=>p.id===patientId);
  const changed=(Object.keys(labels) as (keyof Details)[]).filter(key=>baseline&&(details[key]??'')!==(baseline[key]??''));
  function choosePatient(id:string){setPatientId(id);setConfirmed(false);const patient=options.patients.find(p=>p.id===id);
    setDetails({...empty,...(patient?Object.fromEntries(Object.keys(labels).map(key=>[key,patient[key as keyof Details]])):{}),...scan?.suggestions});}
  async function pick(camera:boolean){setBusy(true);setError('');try{
    if(camera){const permission=await ImagePicker.requestCameraPermissionsAsync();if(!permission.granted)throw new Error('Allow camera access in phone settings, or choose an existing photo.');}
    const config:ImagePicker.ImagePickerOptions={mediaTypes:['images'],base64:true,quality:0.9,allowsEditing:false,exif:false};
    acceptImage(camera?await ImagePicker.launchCameraAsync(config):await ImagePicker.launchImageLibraryAsync(config));
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function recognize(){setBusy(true);setError('');try{
    const draft=await call<Scan>('document-scans/',{image_base64:encoded});setScan(draft);setDetails({...empty,...draft.suggestions});setText(draft.extracted_text);setConfirmed(false);setEncoded('');
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function save(){if(!scan)return;setBusy(true);setError('');try{
    const result=await call<Scan>(`document-scans/${scan.id}/`,{confirmed,patient_id:patientId||null,expected_patient_updated_at:baseline?.updated_at,patient_details:{...details,date_of_birth:details.date_of_birth||null},title,reviewed_text:text});
    setScan(result);setPatientId(result.patient_id??'');setConfirmed(false);await refresh();Alert.alert('Document saved','The original picture, searchable PDF and reviewed text are saved in this patient’s file.');
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function openPDF(){if(!scan)return;setBusy(true);setError('');let uri='';try{
    if(!await Sharing.isAvailableAsync())throw new Error('Use the installed phone app to view the PDF.');
    const data=await call<{base64:string}>(`document-scans/${scan.id}/download/pdf/`);
    if(!FileSystem.cacheDirectory)throw new Error('Phone storage is unavailable.');
    uri=`${FileSystem.cacheDirectory}mediflow-${scan.id}.pdf`;
    await FileSystem.writeAsStringAsync(uri,data.base64,{encoding:FileSystem.EncodingType.Base64});
    await Sharing.shareAsync(uri,{mimeType:'application/pdf',UTI:'com.adobe.pdf',dialogTitle:'Open patient document'});
  }catch(e){setError((e as Error).message);}finally{if(uri)await FileSystem.deleteAsync(uri,{idempotent:true}).catch(()=>{});setBusy(false);}}
  function reset(){setScan(null);setImage('');setEncoded('');setPatientId('');setDetails({...empty});setTitle('Scanned document');setText('');setConfirmed(false);}
  async function discard(){if(!scan||saved){reset();return;}setBusy(true);setError('');try{await call(`document-scans/${scan.id}/`,undefined,'DELETE');reset();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function loadDocument(id:string){setBusy(true);setError('');try{
    const document=await call<Scan>(`document-scans/${id}/`);const original=await call<{base64:string;content_type:string}>(`document-scans/${id}/download/original/`);
    setScan(document);setImage(`data:${original.content_type};base64,${original.base64}`);setText(document.reviewed_text);setTitle(document.title);setPatientId(document.patient_id??'');setConfirmed(false);
    if(!document.reviewed_at)setDetails({...empty,...document.suggestions});
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  return <Screen title="Scan document" subtitle="Photograph the full page in good light. Review every detail before saving to a patient’s file.">
    <ErrorText message={error}/>
    {!scan&&<Card><Text style={s.heading}>1 · Capture a page</Text><Action label="Take a picture" busy={busy} onPress={()=>void pick(true)}/><Action label="Choose a document photo" secondary disabled={busy} onPress={()=>void pick(false)}/></Card>}
    {!!image&&<Card><Image accessibilityLabel="Document picture" source={{uri:image}} style={{width:'100%',height:340}} resizeMode="contain"/></Card>}
    {!scan&&!!encoded&&<Action label="Read document" busy={busy} onPress={()=>void recognize()}/>}
    {scan&&<Card><Text style={s.heading}>{saved?'Saved patient document':'2 · Review recognised details'}</Text>
      {!saved?<><Text style={s.text}>Suggestions can contain mistakes. Choose the correct patient or create a new record. Blank or ambiguous fields need your input.</Text>
        <Action label="Refresh patient directory" secondary disabled={busy} onPress={()=>{setConfirmed(false);void refresh().catch(e=>setError((e as Error).message));}}/>
        <ChoiceField label="Patient" choices={[{id:'',name:'Create a new patient record'},...options.patients]} value={patientId} onChange={choosePatient}/>
        {(Object.keys(labels) as (keyof Details)[]).map(key=><Field key={key} label={labels[key]} value={details[key]??''} multiline={key==='address'} keyboardType={key==='mobile'?'phone-pad':key==='email'?'email-address':'default'} onChangeText={value=>{setDetails({...details,[key]:value});setConfirmed(false);}}/>)}
        {baseline&&<><Text style={s.heading}>Changes to the existing patient</Text>{changed.length?changed.map(key=><Text key={key} style={s.text}>{labels[key]}: {baseline[key]||'(blank)'} → {details[key]||'(blank)'}</Text>):<Text style={s.text}>No changes to patient details.</Text>}</>}
        <Field label="Document title" value={title} onChangeText={setTitle}/><Field label="Recognised text — review and correct" value={text} multiline onChangeText={setText}/>
        <Text style={s.small}>The PDF retains the picture and machine-recognised text. Your corrected text is saved separately alongside it.</Text>
        {!scan.extracted_text.trim()&&<Text style={s.error}>No text was recognised. Enter the details yourself, or discard and take a clearer picture.</Text>}
        <View style={s.row}><Switch accessibilityLabel="I reviewed the document and patient details" value={confirmed} onValueChange={setConfirmed}/><Text style={[s.text,{flex:1}]}>I reviewed the document and approve these patient details.</Text></View>
        <Action label="Approve & save to patient file" busy={busy} disabled={!confirmed||!details.file_number||!details.given_name||!details.family_name||!title.trim()} onPress={()=>Alert.alert('Save reviewed document',baseline?`Save to ${baseline.name}? ${changed.length} patient field(s) will change.`:'Create the reviewed patient record and attach this document?',[{text:'Cancel',style:'cancel'},{text:'Save',onPress:()=>void save()}])}/>
        <Action label="Discard draft" secondary disabled={busy} onPress={()=>Alert.alert('Discard document?','This removes the unreviewed scan.',[{text:'Keep reviewing',style:'cancel'},{text:'Discard',style:'destructive',onPress:()=>void discard()}])}/>
      </>:<><Text style={s.text}>{title}</Text><Text style={s.text}>Patient: {options.patients.find(p=>p.id===scan.patient_id)?.name||'Saved patient'}</Text><Text style={s.text}>{text||'No text extracted'}</Text><Action label="Scan another document" secondary disabled={busy} onPress={reset}/></>}
      <Action label="Open / share searchable PDF" secondary busy={busy} onPress={()=>void openPDF()}/>
    </Card>}
    {!scan&&!!options.drafts.length&&<Card><Text style={s.heading}>Continue reviewing a draft</Text>{options.drafts.map(draft=><Action key={draft.id} label="Review unfinished scan" secondary disabled={busy} onPress={()=>void loadDocument(draft.id)}/>)}</Card>}
    {!scan&&<Card><Text style={s.heading}>Saved documents</Text>{options.documents.length?options.documents.map(document=><Action key={document.id} label={`${document.title} · ${options.patients.find(p=>p.id===document.patient_id)?.name||'Patient'}`} secondary disabled={busy} onPress={()=>void loadDocument(document.id)}/>):<Text style={s.text}>Reviewed documents will appear here.</Text>}</Card>}
    <Action label="Back to reception" secondary disabled={busy} onPress={()=>{if(scan&&!saved)Alert.alert('Document awaiting review','Save or discard this draft before leaving.');else router.replace('/home');}}/>
  </Screen>;
}
