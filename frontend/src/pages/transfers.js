import {transfers,datasets} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';
import {checksum} from '../utils/checksum.js';
import {canonicalizeRows} from '../utils/canonical.js';

const STATUS_TEXT={collecting:'收段中',ready:'齐备待发布',publishing:'发布中',published:'已发布',revoking:'撤销中',revoked:'已撤销',failed:'校验失败'};
const canWrite=()=>session.user.role!=='viewer';

export async function transferPage(){
 workspace.transfers=await transfers.list();
 let selected=workspace.selectedTransferId?await transfers.get(workspace.selectedTransferId).catch(()=>null):null;
 if(!selected&&workspace.transfers.length){selected=await transfers.get(workspace.transfers[0].id);workspace.selectedTransferId=selected.id;}
 return heading('02 / RESUMABLE UPLOAD','夜巡大批分段接入','先登记总段数、总行数与整批指纹；乱序收段、同段重试幂等、异文拒收，重启后可续传，齐备后发布为完整批次。')+
 '<div class="tabs"><a class="tab" href="#/datasets">小批整表接入</a><span class="tab active">大批分段接入</span></div>'+
 '<div class="dataset-grid"><section class="panel"><div class="section-title"><h2>分段批次</h2><span>'+workspace.transfers.length+' 个会话</span></div><div class="batch-list">'+
 (workspace.transfers.map(t=>'<button class="batch-item'+(selected?.id===t.id?' selected':'')+'" data-transfer="'+t.id+'"><strong>'+esc(t.name)+'</strong><span class="status '+esc(t.status)+'">'+esc(STATUS_TEXT[t.status]||t.status)+' · 段 '+t.received_segments+'/'+t.total_segments+' · 行 '+t.received_rows+'/'+t.total_rows+'</span><small>SHA256 '+esc(t.batch_checksum.slice(0,18))+'…</small></button>').join('')||'<p class="empty">尚无分段批次，先在下方登记一个接入会话。</p>')+
 '</div><div class="section-title"><h2>登记新分段批次</h2></div>'+
 '<details class="helper"><summary>从完整 CSV/JSON 生成登记信息（可选）</summary><input type="file" id="plan-file" accept=".json,.csv"><div class="parameter-grid"><label>分段大小（行/段）<input id="plan-size" type="number" value="100" min="1"></label></div><button type="button" class="button small" id="plan-build">计算总段数、总行数与整批指纹</button><p class="hint">仅在本机计算并填充下方登记表，不会上传整表；段文件可用“生成段文件”逐段保存。</p></details>'+
 '<form id="transfer-open-form"><label>批次名称<input name="name" required minlength="2" placeholder="例如：11 月夜巡整批"></label><label>来源文件<input name="source" value="night-patrol.upload" required></label><div class="parameter-grid"><label>总段数<input name="total_segments" type="number" min="1" required></label><label>总行数<input name="total_rows" type="number" min="5" required></label></div><label>整批指纹 SHA256<input name="batch_checksum" required minlength="32" maxlength="64" placeholder="64 位十六进制"></label><button type="submit" class="primary" '+(canWrite()?'':'disabled')+'>登记分段批次</button></form></section>'+
 '<section class="panel">'+(selected?detailPanel(selected):'<div id="transfer-detail"><p class="empty">选择或登记一个分段批次后，在此续传、确认、撤销并核对缺段与最终批次。</p></div>')+'</section></div>';
}

function detailPanel(t){
 const pct=t.total_segments?Math.round(t.received_segments/t.total_segments*100):0;
 const busy=['publishing','revoking'].includes(t.status);
 const actions='<div class="transfer-actions">'+
  '<button class="button small" data-act="confirm" '+(canWrite()&&t.status==='collecting'?'':'disabled')+'>确认齐备并整批校验</button>'+
  '<button class="button small primary" data-act="publish" '+(canWrite()&&t.status==='ready'?'':'disabled')+'>发布完整批次</button>'+
  '<button class="button small danger" data-act="revoke" '+(canWrite()&&['collecting','ready','failed'].includes(t.status)?'':'disabled')+'>撤销批次</button>'+
  '<button class="button small" data-act="refresh">刷新 ↻</button></div>';
 const issues=(t.issue?.problems||[]).map(p=>'<article class="issue"><strong>'+esc(p.message)+'</strong><p class="issue-code">'+esc(p.code)+'</p>'+issueDetail(p)+'</article>').join('');
 const segChips=Array.from({length:t.total_segments},(_,i)=>{
  const got=(t.segments||[]).find(s=>s.segment_index===i);
  return '<span class="seg-chip '+(got?'ok':'miss')+'" title="'+(got?'已收 '+got.row_count+' 行':'缺段')+'">'+i+'</span>';
 }).join('');
 return '<div id="transfer-detail"><div class="section-title"><h2>'+esc(t.name)+'</h2><span class="status '+esc(t.status)+'">'+esc(STATUS_TEXT[t.status]||t.status)+'</span></div>'+
 '<div class="progress"><div class="progress-bar" style="width:'+pct+'%"></div></div>'+
 '<p class="hint">进度 '+t.received_segments+'/'+t.total_segments+' 段（'+pct+'%）· 已收 '+t.received_rows+'/'+t.total_rows+' 行 · 登记指纹 '+esc(t.batch_checksum)+(t.dataset_id?' · 已发布为数据批次 #'+t.dataset_id:'')+'</p>'+
 actions+
 (t.status==='revoked'?'<p class="warning">该批次已撤销，已收分段已清理；迟到收段或发布不会复活本批次。</p>':'')+
 (t.status==='published'?'<p class="warning">发布完成，最终批次可在“小批整表接入”列表与分析工作台中使用。重复发布不会重复成批。</p>':'')+
 (busy?'<p class="warning">操作进行中，刷新可恢复到原次操作，并发确认不会重复成批。</p>':'')+
 '<div class="section-title compact-title"><h2>缺段核对</h2><span>'+t.missing_count+' 个缺段</span></div><div class="seg-chips">'+segChips+'</div>'+
 (t.status==='collecting'?'<div class="section-title compact-title"><h2>续传 / 补段（支持乱序）</h2></div>'+
  '<details class="helper" open><summary>段信封 JSON（segment_index / row_count / checksum / records）</summary><input type="file" id="segment-file" accept=".json"><textarea id="segment-text" rows="8" placeholder="粘贴段信封 JSON，或选择段文件"></textarea><button type="button" class="button small" id="segment-send" '+(canWrite()?'':'disabled')+'>校验并接收本段</button><button type="button" class="button small" id="segment-make" '+(canWrite()?'':'disabled')+'>用整表生成段文件</button><p class="hint">同段重复提交且指纹一致时幂等不重复计入；指纹不同按异文拒收，不覆盖已收内容。</p></details>':'')+
 (t.segments?.length?'<div class="section-title compact-title"><h2>已收分段</h2><span>'+t.segments.length+' 段</span></div><div class="table-wrap"><table><thead><tr><th>段号</th><th>行数</th><th>段指纹</th><th>接收时间</th></tr></thead><tbody>'+
  t.segments.map(s=>'<tr><td>'+s.segment_index+'</td><td>'+s.row_count+'</td><td>'+esc(s.checksum.slice(0,24))+'…</td><td>'+new Date(s.received_at*1000).toLocaleString('zh-CN',{hour12:false})+'</td></tr>').join('')+'</tbody></table></div>':'')+
 (issues?'<div class="section-title compact-title"><h2>整批校验定位</h2><span>已保留全部已收内容</span></div><div class="issue-list">'+issues+'</div>':'')+'</div>';
}

function issueDetail(p){
 if(p.code==='missing_segments')return '<p>缺段号：'+p.missing_segments.join(', ')+(p.missing_total>p.missing_segments.length?' …（共 '+p.missing_total+' 段）':'')+'</p>';
 if(p.code==='duplicate_segment_id')return '<div class="table-wrap"><table><tbody>'+p.duplicates.map(d=>'<tr><td>'+esc(d.segment_id)+'</td><td>'+d.occurrences.map(o=>'段'+o.segment+' 第'+o.row+'行').join('；')+'</td></tr>').join('')+'</tbody></table></div>';
 if(p.code==='row_total_mismatch')return '<p>登记 '+p.expected_rows+' 行，实收 '+p.actual_rows+' 行。</p>';
 if(p.code==='checksum_mismatch')return '<p>登记 '+esc(p.expected_checksum)+'<br>实算 '+esc(p.actual_checksum)+'</p>';
 if(p.code==='invalid_rows')return '<div class="table-wrap"><table><tbody>'+p.row_errors.map(e=>'<tr><td>段'+e.segment+' 第'+e.row+'行</td><td>'+esc(e.field)+'</td><td>'+esc(e.message)+'</td></tr>').join('')+'</tbody></table></div>';
 return '';
}

async function currentDetail(){return transfers.get(workspace.selectedTransferId);}
export function bindTransfers(refresh){
 document.querySelectorAll('[data-transfer]').forEach(b=>b.onclick=async()=>{workspace.selectedTransferId=Number(b.dataset.transfer);await refresh();});
 document.querySelector('#plan-file')?.addEventListener('change',planFromFile);
 document.querySelector('#plan-build')?.addEventListener('click',buildPlan);
 submit(document.querySelector('#transfer-open-form'),async f=>{
  const created=await transfers.open({name:f.get('name'),source:f.get('source'),total_segments:Number(f.get('total_segments')),total_rows:Number(f.get('total_rows')),batch_checksum:f.get('batch_checksum').trim().toLowerCase()});
  workspace.selectedTransferId=created.id;notify('分段批次已登记，可开始续传');await refresh();
 });
 bindDetail(refresh);
}

function bindDetail(refresh){
 const act=document.querySelector('#transfer-detail .transfer-actions');
 act?.querySelectorAll('[data-act]').forEach(b=>b.onclick=()=>runAction(b.dataset.act,refresh));
 document.querySelector('#segment-file')?.addEventListener('change',async e=>{
  const file=e.target.files[0];if(!file)return;
  document.querySelector('#segment-text').value=await file.text();
 });
 document.querySelector('#segment-send')?.addEventListener('click',sendSegment);
 document.querySelector('#segment-make')?.addEventListener('click',makeSegmentFiles);
}

async function runAction(name,refresh){
 const id=workspace.selectedTransferId;
 try{
  if(name==='refresh'){await refresh();return;}
  if(name==='confirm'){await transfers.confirm(id);notify('齐备确认通过，可发布完整批次');}
  if(name==='publish'){const t=await currentDetail();const r=await transfers.publish(id,t.batch_checksum);notify(r.reused?'该批次此前已发布，未重复成批':'完整批次已发布：数据批次 #'+r.dataset_id);await datasets.list();}
  if(name==='revoke'){if(!confirm('确认撤销该分段批次？已收分段将被清理，且迟到收段/发布不会复活。'))return;await transfers.revoke(id);notify('批次已撤销');}
  await refresh();
 }catch(e){notify(e.message,true);await refresh().catch(()=>{});}
}

async function sendSegment(){
 const id=workspace.selectedTransferId;
 try{
  const env=JSON.parse(document.querySelector('#segment-text').value);
  for(const k of ['segment_index','row_count','checksum','records']){if(!(k in env))throw new Error('段信封缺少字段 '+k);}
  if(!Array.isArray(env.records)||env.records.length!==env.row_count)throw new Error('row_count 与 records 行数不一致');
  canonicalizeRows(env.records,workspace.meta.columns,Number(env.segment_index));
  const local=await checksum(env.records);
  if(local!==String(env.checksum).toLowerCase())throw new Error('段指纹与内容不一致（本地复算 '+local.slice(0,16)+'…），请核对段文件');
  const r=await transfers.segment(id,{segment_index:Number(env.segment_index),row_count:env.row_count,checksum:env.checksum.toLowerCase(),records:env.records});
  notify(r.duplicate?'同段重试：指纹一致，幂等未重复计入':'第 '+env.segment_index+' 段已接收（'+env.row_count+' 行）');
  const t=await currentDetail();
  document.querySelector('#transfer-detail').outerHTML=detailWrap(t);bindDetail();
 }catch(e){notify(e.message,true);}
}

function detailWrap(t){
 const html=detailPanel(t);
 const start=html.indexOf('<div id="transfer-detail">');
 return html.slice(start);
}

async function readPlanFile(){
 const file=document.querySelector('#plan-file').files[0];
 if(!file)throw new Error('请先选择完整 CSV 或 JSON 文件');
 const text=await file.text();
 return file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);
}

async function buildPlan(){
 try{
  const records=await readPlanFile();
  if(!Array.isArray(records)||!records.length)throw new Error('文件内容不是记录数组');
  canonicalizeRows(records,workspace.meta.columns);
  const size=Math.max(1,Number(document.querySelector('#plan-size').value)||100);
  const form=document.querySelector('#transfer-open-form');
  form.total_segments.value=Math.ceil(records.length/size);
  form.total_rows.value=records.length;
  form.batch_checksum.value=await checksum(records);
  notify('已计算总段数、总行数与整批指纹');
 }catch(e){notify(e.message,true);}
}

async function planFromFile(e){
 // 选择文件即准备好记录，点击“生成段文件”时复用
 const file=e.target.files[0];if(file)notify('已选择 '+file.name+'，点击计算或生成段文件');
}

async function makeSegmentFiles(){
 try{
  const records=await readPlanFile();
  canonicalizeRows(records,workspace.meta.columns);
  const size=Math.max(1,Number(document.querySelector('#plan-size').value)||100);
  const total=Math.ceil(records.length/size);
  const pick=prompt('要生成哪一段（0~'+(total-1)+'）？将下载段信封 JSON。','0');
  if(pick===null)return;
  const index=Number(pick);
  if(!Number.isInteger(index)||index<0||index>=total)throw new Error('段号超出范围');
  const part=records.slice(index*size,index*size+size);
  const env={segment_index:index,row_count:part.length,checksum:await checksum(part),records:part};
  const blob=new Blob([JSON.stringify(env,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download='segment-'+index+'.json';a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  document.querySelector('#segment-text').value=JSON.stringify(env,null,2);
  notify('段文件已生成并填入续传框');
 }catch(e){notify(e.message,true);}
}
