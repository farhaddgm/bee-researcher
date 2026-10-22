/* Static AST extraction plus executable catalog checks. Never execute UI controllers. */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import {parse} from 'acorn';
import {fileURLToPath} from 'node:url';
export const languages=['fa','en','tr','ar','es','it','de','fr'];
const root=fileURLToPath(new URL('../app/',import.meta.url));
const rows=new Map(), errors=[];
const isLanguage=key=>languages.includes(key);
const keyOf=node=>node?.name??node?.value;
const placeholders=value=>JSON.stringify((value.match(/\$\{[^}]+\}|\{[A-Za-z_][\w.]*\}|%\d*\$?[sd]/g)||[]).sort());
function literal(node){
  if(node?.type==='Literal')return node.value;
  if(node?.type==='TemplateLiteral'&&!node.expressions.length)return node.quasis[0].value.cooked;
  if(node?.type==='ArrayExpression')return node.elements.map(literal);
  return undefined;
}
function add(file,key,translations){
  if(!languages.every(lang=>typeof translations[lang]==='string'&&translations[lang].trim()))return;
  for(const language of languages)if(placeholders(translations[language])!==placeholders(translations.en))errors.push(file+': placeholder mismatch '+key+' '+language);
  const entry={id:rows.size,file,key,translations};
  const identity=JSON.stringify([file,key]);
  // Identical source locations are replaced, not counted twice.
  rows.set(identity,entry);
}
function walk(node,file){
  if(!node||typeof node!=='object')return;
  if(node.type==='ObjectExpression'){
    const properties=node.properties.filter(p=>p.type==='Property'&&!p.computed);
    const langs=properties.filter(p=>isLanguage(keyOf(p.key)));
    if(langs.length===8){
      const values=Object.fromEntries(langs.map(p=>[keyOf(p.key),literal(p.value)]));
      if(languages.every(l=>typeof values[l]==='string'))add(file,'@'+node.start,values);
      else if(languages.every(l=>Array.isArray(values[l]))){
        const count=values.en.length;
        if(!languages.every(l=>values[l].length===count))errors.push(file+': unequal locale array lengths @'+node.start);
        else for(let i=0;i<count;i++)add(file,'@'+node.start+'['+i+']',Object.fromEntries(languages.map(l=>[l,values[l][i]])));
      }
    }
  }
  for(const [key,value]of Object.entries(node)){
    if(key==='start'||key==='end')continue;
    if(Array.isArray(value))for(const child of value)walk(child,file);
    else if(value&&typeof value==='object')walk(value,file);
  }
}
function files(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(path.join(dir,e.name)):[path.join(dir,e.name)]);}
for(const file of files(root).filter(x=>x.endsWith('.js'))){
  const relative=path.relative(root,file),source=fs.readFileSync(file,'utf8');
  const sourceType=/^\s*(?:import|export)\s/m.test(source)?'module':'script';
  walk(parse(source,{ecmaVersion:'latest',sourceType}),relative);
}
const sandbox={window:{},document:{documentElement:{lang:'en'}},localStorage:{getItem:()=>null},crypto};
const context=vm.createContext(sandbox);
for(const file of ['news_chat/i18n.js','news_voice/i18n.js','news_voice/admin-i18n.js','reader_tools/i18n.js','reader_research/i18n.js','token_quotas/i18n.js','analysis_lenses/i18n.js','report_portal/i18n.js']){
  vm.runInContext(fs.readFileSync(path.join(root,file),'utf8'),context,{filename:file,timeout:1000});
}
for(const name of ['BeeNewsChatI18n','BeeTokenI18n','BeeReportI18n']){
  const catalog=sandbox.window[name];if(!catalog)throw Error('Missing catalog '+name);
  const langs=catalog.languages||catalog.langs;
  for(const [key,values]of Object.entries(catalog.words||catalog.rows)){
    if(!Array.isArray(values)||values.length!==8||values.some(v=>typeof v!=='string'||!v.trim()))errors.push(name+': invalid '+key);
    else add(name,key,Object.fromEntries(langs.map((lang,index)=>[lang,values[index]])));
  }
}
const lens=sandbox.window.BeeLensI18n;
for(const key of lens.keys)add('analysis_lenses/i18n.js',key,Object.fromEntries(languages.map(lang=>[lang,lens.catalog[lang][key]])));
const merged={};
for(const file of ['ux_writing_catalog.json','ux_writing_catalog_additions.json'])Object.assign(merged,JSON.parse(fs.readFileSync(path.join(root,file),'utf8')));
for(const [key,translations]of Object.entries(merged)){
  if(key.startsWith("'+")||key.includes('+label(')||key.includes('+esc('))continue;
  add('admin-catalog',key,{fa:key,...translations});
}
const entries=[...rows.values()].map((row,id)=>({...row,id}));
const output={schema_version:1,languages,entries,errors,
  coverage:{entries:entries.length,localized_values:entries.length*8,files:[...new Set(entries.map(row=>row.file))].sort()},
  limitations:['Static catalog extraction is not full runtime coverage.','Automated or model review is not independent human acceptance.'],
  human_review:false};
output.source_digest=crypto.createHash('sha256').update(JSON.stringify(entries)).digest('hex');
if(process.argv.includes('--summary'))console.log(JSON.stringify({...output,entries:undefined}));
else console.log(JSON.stringify(output,null,2));
if(errors.length)process.exitCode=1;
