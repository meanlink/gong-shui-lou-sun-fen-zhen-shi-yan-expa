// 与后端 services/canonical.py 对齐的行规范化：数值列统一 float、管号列统一非空字符串。
// 规范化后两端计算出的 SHA256 才一致；任何字段问题抛出带定位的错误。
export function canonicalizeRows(records, columns, segmentIndex=null){
 const where=segmentIndex===null?'':`第 ${segmentIndex} 段`;
 records.forEach((row,offset)=>{
  const at=where+`第 ${offset+1} 行`;
  if(!row||typeof row!=='object'||Array.isArray(row))throw new Error(at+' 不是有效记录对象');
  for(const c of columns){
   const v=row[c.key];
   if(v===null||v===undefined||v==='')throw new Error(at+' 缺少字段 '+c.label);
   if(c.type==='number'){
    if(typeof v==='boolean')throw new Error(at+' '+c.label+' 必须为有限数值');
    const n=Number(v);
    if(!Number.isFinite(n))throw new Error(at+' '+c.label+' 必须为有限数值');
    row[c.key]=n;
   }else{
    if(typeof v==='object'||!String(v).trim())throw new Error(at+' '+c.label+' 不能为空');
    row[c.key]=String(v);
   }
  }
 });
 return records;
}
