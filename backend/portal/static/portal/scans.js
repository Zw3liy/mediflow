'use strict';
(() => {
  const root = document.getElementById('document-scanner');
  if (!root) return;
  const el = id => document.getElementById(`scan-${id}`);
  const practice = root.dataset.practice;
  const fields = ['file_number','given_name','family_name','date_of_birth','mobile','email','address'];
  let patients = [], draft = null, busy = false;
  const endpoint = path => `/app/scans/api/${path}?practice=${encodeURIComponent(practice)}`;
  async function api(path, body, method) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 70000);
    try {
      const response = await fetch(endpoint(path), {method:method || (body === undefined ? 'GET':'POST'),
        credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRFToken':root.querySelector('[name=csrfmiddlewaretoken]').value},
        body:body === undefined ? undefined : JSON.stringify(body), signal:controller.signal});
      if(response.status===204)return {};
      const data = await response.json();
      if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data));
      return data;
    } finally { clearTimeout(timer); }
  }
  async function run(action) {
    if(busy)return;
    busy=true;el('error').textContent='';el('status').textContent='Please wait…';
    root.querySelectorAll('button').forEach(button=>button.disabled=true);
    try { await action(); } catch(error) { el('error').textContent=error.name==='AbortError'?'The request took too long. Refresh the draft list before retrying.':error.message; }
    finally { busy=false;root.querySelectorAll('button').forEach(button=>button.disabled=false);el('status').textContent=''; }
  }
  function changes() {
    const patient=patients.find(p=>p.id===el('patient').value);
    const changed=fields.filter(field=>patient&&(patient[field]||'')!==el(field).value);
    el('changes').replaceChildren();
    if(!patient)return;
    const heading=document.createElement('h3');heading.textContent='Changes to existing patient';el('changes').append(heading);
    if(!changed.length){const p=document.createElement('p');p.textContent='No changes to patient details.';el('changes').append(p);}
    changed.forEach(field=>{const p=document.createElement('p');p.textContent=`${field.replaceAll('_',' ')}: ${patient[field]||'(blank)'} → ${el(field).value||'(blank)'}`;el('changes').append(p);});
  }
  function selectPatient() {
    const patient=patients.find(p=>p.id===el('patient').value);
    fields.forEach(field=>el(field).value=draft?.suggestions[field]??patient?.[field]??'');
    el('confirmed').checked=false;changes();
  }
  function reset() {draft=null;el('review').hidden=true;el('saved').hidden=true;el('preview').hidden=true;el('pdf').hidden=true;el('upload').hidden=false;el('image').value='';}
  const certificateLabels = ['Patient full name', 'Document type', 'Practitioner name', 'Date of first consultation', 'Follow-up consultation date', 'Unfit for duty from', 'Unfit for duty to', 'Nature of illness or injury', 'Work can be resumed on', 'Certificate date', 'Comments'];
  function addDocumentField(label='', value='') {
    const row=document.createElement('div');row.className='scan-document-field';
    const name=document.createElement('input');name.value=label;name.maxLength=100;name.placeholder='Field name';name.setAttribute('aria-label','Document field name');name.required=true;
    const entry=document.createElement('textarea');entry.value=value;entry.maxLength=2000;entry.rows=2;entry.placeholder='Not confidently read — enter after checking the picture';entry.setAttribute('aria-label',label||'Document field value');
    const remove=document.createElement('button');remove.type='button';remove.className='button secondary';remove.textContent='Remove field';remove.addEventListener('click',()=>{row.remove();el('confirmed').checked=false;});
    [name,entry].forEach(input=>input.addEventListener('input',()=>{el('confirmed').checked=false;}));
    const nameLabel=document.createElement('label');nameLabel.textContent='Field name';nameLabel.append(name);const valueLabel=document.createElement('label');valueLabel.textContent='Reviewed value';valueLabel.append(entry);row.append(nameLabel,valueLabel,remove);el('document-fields').append(row);
  }
  el('add-field').addEventListener('click',()=>{if(el('document-fields').children.length<50)addDocumentField();});
  function documentFields() {return Array.from(el('document-fields').children).map(row=>({label:row.querySelector('input').value,value:row.querySelector('textarea').value}));}
  function show(scan) {
    el('document-fields').replaceChildren();
    (scan.document_fields?.length?scan.document_fields:certificateLabels.map(label=>({label,value:''}))).forEach(field=>addDocumentField(field.label,field.value));
    draft=scan;el('upload').hidden=true;el('preview').src=endpoint(`${scan.id}/download/original/`);el('preview').hidden=false;
    el('pdf').href=endpoint(`${scan.id}/download/pdf/`);el('pdf').hidden=false;
    el('review').hidden=!!scan.reviewed_at;el('saved').hidden=!scan.reviewed_at;
    if(scan.reviewed_at){el('saved-info').textContent=`${scan.title} · ${patients.find(p=>p.id===scan.patient_id)?.name||'Patient'}`;el('saved-text').textContent=scan.reviewed_text+'\n\n'+(scan.document_fields||[]).map(field=>`${field.label}: ${field.value}`).join('\n');}
    else {el('patient').value='';el('title').value=scan.title;el('text').value=scan.reviewed_text;selectPatient();}
  }
  async function refresh() {
    const data=await api('');const selected=el('patient').value;patients=data.patients;
    el('patient').replaceChildren(new Option('Create a new patient record',''));
    patients.forEach(patient=>el('patient').add(new Option(patient.name,patient.id)));
    el('patient').value=selected;
    for(const [name,items] of [['drafts',data.drafts],['documents',data.documents]]){
      el(name).replaceChildren();
      if(!items.length){const p=document.createElement('p');p.textContent=name==='drafts'?'No unfinished drafts.':'No saved documents yet.';el(name).append(p);}
      items.forEach(scan=>{const button=document.createElement('button');button.type='button';button.className='button secondary';button.textContent=scan.reviewed_at?`${scan.title} · ${patients.find(p=>p.id===scan.patient_id)?.name||'Patient'}`:'Review unfinished scan';button.addEventListener('click',()=>run(async()=>{if(draft&&!draft.reviewed_at)throw new Error('Save or discard the current draft first.');show(await api(`${scan.id}/`));}));el(name).append(button);});
    }
  }
  el('upload').addEventListener('submit',event=>{event.preventDefault();void run(async()=>{
    const file=el('image').files[0];if(!file||file.size>8*1024*1024)throw new Error('Choose a JPEG or PNG picture up to 8 MB.');
    const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('Could not read the picture.'));reader.readAsDataURL(file);});
    show(await api('',{image_base64:encoded}));await refresh();
  });});
  ['text','title'].forEach(id=>el(id).addEventListener('input',()=>{el('confirmed').checked=false;}));
  el('patient').addEventListener('change',selectPatient);
  fields.forEach(field=>el(field).addEventListener('input',()=>{el('confirmed').checked=false;changes();}));
  el('refresh').addEventListener('click',()=>run(async()=>{await refresh();selectPatient();}));
  el('review').addEventListener('submit',event=>{event.preventDefault();void run(async()=>{
    const patient=patients.find(p=>p.id===el('patient').value);
    if(!el('confirmed').checked)throw new Error('Review and approve the patient details.');
    if(!window.confirm(patient?`Save to ${patient.name} and approve the displayed changes?`:'Create the reviewed patient record and attach this document?'))return;
    const details=Object.fromEntries(fields.map(field=>[field,el(field).value]));details.date_of_birth=details.date_of_birth||null;
    const result=await api(`${draft.id}/`,{confirmed:true,patient_id:patient?.id||null,expected_patient_updated_at:patient?.updated_at,
      patient_details:details,document_fields:documentFields(),title:el('title').value,reviewed_text:el('text').value});
    await refresh();show(result);
  });});
  el('discard').addEventListener('click',()=>run(async()=>{if(!window.confirm('Discard this unfinished scan?'))return;await api(`${draft.id}/`,undefined,'DELETE');reset();await refresh();}));
  el('another').addEventListener('click',reset);
  window.addEventListener('beforeunload',event=>{if(draft&&!draft.reviewed_at){event.preventDefault();event.returnValue='';}});
  void run(refresh);
})();
