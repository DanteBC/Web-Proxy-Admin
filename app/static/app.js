async function api(url, options={}){const r=await fetch(url,options);if(!r.ok)throw new Error((await r.text()).slice(0,300));return r.json()}
async function users(){const rows=await api('/api/users');document.querySelector('#users').innerHTML=rows.map(r=>`<tr><td>${escape(r.login)}</td><td>${r.enabled}</td><td><button data-delete-user="${r.id}">Delete</button></td></tr>`).join('')}
async function rules(){const rows=await api('/api/routes');document.querySelector('#rules').innerHTML=rows.map(r=>`<tr><td>${escape(r.cidr)}</td><td>${escape(r.kind)}</td><td><button data-delete-rule="${r.id}">Delete</button></td></tr>`).join('')}
async function usage(){const rows=await api('/api/statistics');document.querySelector('#usage').innerHTML=rows.map(r=>`<tr><td><button class="user-usage-link" type="button" data-usage-user="${encodeURIComponent(r.proxy_user)}">${escape(r.proxy_user)}</button></td><td>${r.day}</td><td>${r.bytes_in}</td><td>${r.bytes_out}</td><td>${r.sessions}</td></tr>`).join('')}
function formatBytes(bytes){const units=['B','KiB','MiB','GiB','TiB'];let value=Number(bytes)||0,index=0;while(value>=1024&&index<units.length-1){value/=1024;index++}return `${value.toFixed(index===0?0:2)} ${units[index]}`}
async function userUsage(username){
 const detail=document.querySelector('#user-usage-detail')
 detail.hidden=false
 detail.innerHTML='<p>Загрузка статистики…</p>'
 const data=await api(`/api/statistics/user?username=${encodeURIComponent(username)}`)
 detail.innerHTML=`<div class="user-usage-heading"><h3>Статистика пользователя: ${escape(data.proxy_user)}</h3><button type="button" id="close-user-usage">Закрыть</button></div>
 <div class="usage-summary"><div><strong>Сегодня</strong><span>Вход: ${formatBytes(data.today.bytes_in)} · Выход: ${formatBytes(data.today.bytes_out)} · Сессии: ${data.today.sessions}</span></div>
 <div><strong>Текущий месяц</strong><span>Вход: ${formatBytes(data.month.bytes_in)} · Выход: ${formatBytes(data.month.bytes_out)} · Сессии: ${data.month.sessions}</span></div></div>
 <h4>По дням текущего месяца</h4>
 ${data.days.length?`<div class="usage-days"><table><thead><tr><th>Дата</th><th>Вход</th><th>Выход</th><th>Сессии</th></tr></thead><tbody>${data.days.map(row=>`<tr><td>${escape(row.day)}</td><td>${formatBytes(row.bytes_in)}</td><td>${formatBytes(row.bytes_out)}</td><td>${row.sessions}</td></tr>`).join('')}</tbody></table></div>`:'<p class="status-empty">За текущий месяц данных нет</p>'}`
 document.querySelector('#close-user-usage').onclick=()=>{detail.hidden=true;detail.innerHTML=''}
}
let routeStatusMode='table'
const statusLabels={ipsets:'IP sets',iptables:'iptables (mangle)',rules:'IP rules',routes:'Routes'}
function statusLines(value){return String(value??'').split(/\r?\n/).map(line=>line.trimEnd()).filter(line=>line.trim())}
function renderIpSets(value){
 const lines=statusLines(value),sets=[]
 let current=null,members=false
 for(const line of lines){
  const name=line.match(/^Name:\s*(.+)$/)
  if(name){current={name:name[1],fields:[],members:[]};sets.push(current);members=false;continue}
  if(!current)continue
  if(/^Members:\s*$/.test(line)){members=true;continue}
  if(members){current.members.push(line.trim());continue}
  const field=line.match(/^\s*([^:]+):\s*(.*)$/)
  if(field)current.fields.push([field[1].trim(),field[2].trim()])
 }
 if(!sets.length)return renderLinesTable(value,'Параметр или запись')
 return `<table><thead><tr><th>Набор</th><th>Параметр</th><th>Значение</th></tr></thead><tbody>${sets.map(set=>{
  const rows=set.fields.map(([field,fieldValue])=>`<tr><td>${escape(set.name)}</td><td>${escape(field)}</td><td>${escape(fieldValue)}</td></tr>`)
  rows.push(`<tr><td>${escape(set.name)}</td><td>Members</td><td><details><summary>${set.members.length} записей</summary><pre>${escape(set.members.join('\n'))}</pre></details></td></tr>`)
  return rows.join('')
 }).join('')}</tbody></table>`
}
function renderLinesTable(value,column){
 const lines=statusLines(value)
 if(!lines.length)return '<p class="status-empty">Нет данных</p>'
 return `<table><thead><tr><th>#</th><th>${escape(column)}</th></tr></thead><tbody>${lines.map((line,index)=>`<tr><td>${index+1}</td><td class="status-line">${escape(line)}</td></tr>`).join('')}</tbody></table>`
}
function setRouteStatusMode(mode){
 routeStatusMode=mode
 const tableMode=mode==='table'
 document.querySelector('#route-status-table').hidden=!tableMode
 document.querySelector('#route-status-text').hidden=tableMode
 document.querySelector('#status-table-toggle').setAttribute('aria-pressed',String(tableMode))
 document.querySelector('#status-text-toggle').setAttribute('aria-pressed',String(!tableMode))
}
async function routeStatus(){
 const data=await api('/api/routes/status')
 const table=document.querySelector('#route-status-table')
 table.innerHTML=Object.entries(data).map(([name,value])=>{
  const label=statusLabels[name]||name
  const body=name==='ipsets'?renderIpSets(value):renderLinesTable(value,'Правило или маршрут')
  return `<section class="status-section"><h3>${escape(label)}</h3>${body}</section>`
 }).join('')
 document.querySelector('#route-status-text').textContent=JSON.stringify(data,null,2)
 setRouteStatusMode(routeStatusMode)
}
function escape(v){const d=document.createElement('div');d.textContent=v;return d.innerHTML}
document.querySelector('#add-user').onclick=async()=>{await api('/api/users',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({login:document.querySelector('#login').value,password:document.querySelector('#password').value})});await users()}
document.querySelector('#add-rule').onclick=async()=>{await api('/api/routes',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({cidr:document.querySelector('#cidr').value,kind:document.querySelector('#kind').value})});await rules()}
document.querySelector('#apply-rules').onclick=async()=>{await api('/api/routes/apply',{method:'POST'});await routeStatus()}
document.querySelector('#users').onclick=async e=>{if(e.target.dataset.deleteUser){await api('/api/users/'+e.target.dataset.deleteUser,{method:'DELETE'});await users()}}
document.querySelector('#rules').onclick=async e=>{if(e.target.dataset.deleteRule){await api('/api/routes/'+e.target.dataset.deleteRule,{method:'DELETE'});await rules()}}
document.querySelector('#usage').onclick=async e=>{const button=e.target.closest('[data-usage-user]');if(button)await userUsage(decodeURIComponent(button.dataset.usageUser))}
document.querySelector('#status-table-toggle').onclick=()=>setRouteStatusMode('table')
document.querySelector('#status-text-toggle').onclick=()=>setRouteStatusMode('text')
Promise.all([users(),rules(),usage(),routeStatus()])
