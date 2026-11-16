// 与后端 checksum 对齐：UTF-8 字节流上的 SHA256；紧凑规范 JSON（键排序、无空格、非 ASCII 原样）。
// 数值渲染对齐 Python repr(float)：V8 的 Number.toString 与 CPython dtoa 都采用最短往返表示，
// 差异只在记法选择（Python：abs>=1e16 或 abs<1e-4 用科学计数法）与指数格式（两位补零带符号）。
function padExponent(exp){
 return 'e'+(exp<0?'-':'+')+Math.abs(exp).toString().padStart(2,'0');
}
// 入参为不含 'e' 的定点数字文本，输出 Python 风格科学计数法文本。
function fixedToScientific(raw){
 const neg=raw.startsWith('-');
 const unsigned=neg?raw.slice(1):raw;
 const [intPart,fracPart='']=unsigned.split('.');
 const leadingZeros=(intPart.match(/^0+/)||[''])[0].length;
 const digits=intPart+fracPart;                 // 含前导零的完整数字串
 const pointPos=intPart.length;                 // 小数点在 digits 中的位置
 const firstSig=digits.search(/[1-9]/);         // 首个有效数字下标
 const exp=pointPos-firstSig-1;
 const significant=digits.slice(firstSig).replace(/0+$/,'');
 // Python 科学计数法尾数：单位有效数字直接写整数（1e+16），多位才带小数点（1.23e+16）
 const mantissa=significant.length===1?significant:significant[0]+'.'+significant.slice(1);
 return (neg?'-':'')+mantissa+padExponent(exp);
}
function pythonReprFloat(n){
 if(Object.is(n,-0))return '-0.0';
 if(n===0)return '0.0';
 const raw=String(n);
 const abs=Math.abs(n);
 if(raw.includes('e')){
  const [mantissa,expRaw]=raw.split('e');
  return mantissa+padExponent(Number(expRaw));
 }
 if(abs>=1e16||abs<1e-4)return fixedToScientific(raw);
 if(Number.isInteger(n))return raw+'.0';
 return raw;
}
function stableStringify(value){
 if(value===null)return 'null';
 const t=typeof value;
 if(t==='number'){
  if(!Number.isFinite(value))throw new Error('存在非有限数值，无法计算校验值');
  return pythonReprFloat(value);
 }
 if(t==='boolean')return value?'true':'false';
 if(t==='string')return JSON.stringify(value);
 if(Array.isArray(value))return '['+value.map(stableStringify).join(',')+']';
 if(t==='object'){
  return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+stableStringify(value[k])).join(',')+'}';
 }
 throw new Error('不支持的字段类型：'+t);
}
export async function checksum(value){
 const bytes=new TextEncoder().encode(stableStringify(value));
 const digest=await crypto.subtle.digest('SHA-256',bytes);
 return Array.from(new Uint8Array(digest)).map(b=>b.toString(16).padStart(2,'0')).join('');
}
