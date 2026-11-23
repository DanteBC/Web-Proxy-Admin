async function api(url, options={}){const r=await fetch(url,options);if(!r.ok)throw new Error((await r.text()).slice(0,300));return r.json()}
async function users(){const rows=await api('/api/users');document.querySelector('#users').innerHTML=rows.map(r=>`<tr><td>${escape(r.login)}</td><td>${r.enabled}</td><td><button data-delete-user="${r.id}">Delete</button></td></tr>`).join('')}
async function rules(){const rows=await api('/api/routes');document.querySelector('#rules').innerHTML=rows.map(r=>`<tr><td>${escape(r.cidr)}</td><td>${escape(r.kind)}</td><td><button data-delete-rule="${r.id}">Delete</button></td></tr>`).join('')}
async function usage(){const rows=await api('/api/statistics');document.querySelector('#usage').innerHTML=rows.map(r=>`<tr><td>${escape(r.proxy_user)}</td><td>${r.day}</td><td>${r.bytes_in}</td><td>${r.bytes_out}</td><td>${r.sessions}</td></tr>`).join('')}
async function routeStatus(){document.querySelector('#route-status').textContent=JSON.stringify(await api('/api/routes/status'),null,2)}
function escape(v){const d=document.createElement('div');d.textContent=v;return d.innerHTML}
document.querySelector('#add-user').onclick=async()=>{await api('/api/users',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({login:document.querySelector('#login').value,password:document.querySelector('#password').value})});await users()}
document.querySelector('#add-rule').onclick=async()=>{await api('/api/routes',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({cidr:document.querySelector('#cidr').value,kind:document.querySelector('#kind').value})});await rules()}
document.querySelector('#apply-rules').onclick=async()=>{await api('/api/routes/apply',{method:'POST'});await routeStatus()}
document.querySelector('#users').onclick=async e=>{if(e.target.dataset.deleteUser){await api('/api/users/'+e.target.dataset.deleteUser,{method:'DELETE'});await users()}}
document.querySelector('#rules').onclick=async e=>{if(e.target.dataset.deleteRule){await api('/api/routes/'+e.target.dataset.deleteRule,{method:'DELETE'});await rules()}}
Promise.all([users(),rules(),usage(),routeStatus()])
