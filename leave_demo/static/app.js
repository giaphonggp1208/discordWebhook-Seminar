const $ = id => document.getElementById(id);
let csrf, timer, refreshing = false;
const labels = {PENDING:'CHỜ DUYỆT',APPROVED:'ĐÃ DUYỆT',REJECTED:'KHÔNG ĐƯỢC CHẤP THUẬN'};
function text(tag, value, className) { const el = document.createElement(tag); el.textContent = value; if(className) el.className = className; return el; }
function notice(message, error=false) { $('notice').hidden=false; $('notice').textContent=message; $('notice').className=error?'error':''; }
async function api(path, options={}) {
  const method = options.method || 'GET';
  const headers = {...options.headers};
  if(method !== 'GET') { if(!csrf) csrf=await api('/api/csrf'); headers[csrf.headerName]=csrf.token; }
  const url = new URL(path, window.location.origin);
  const response = await fetch(url, {...options, headers, credentials:'same-origin'});
  const result = await response.json().catch(()=>({error:'Phản hồi không hợp lệ.'}));
  if(!response.ok) { const err = new Error(result.error || 'Không thể kết nối.'); err.payload=result; throw err; }
  return result;
}
function date(value) { return new Date(value+'T00:00:00').toLocaleDateString('vi-VN'); }
function renderRequests(items) {
  $('request-list').replaceChildren();
  if(!items.length) $('request-list').append(text('p','Chưa có yêu cầu nào.\nTạo đơn đầu tiên ở biểu mẫu bên cạnh.','empty'));
  for(const item of items) {
    const card=text('article','','request'), row=text('div','','request-top');
    row.append(text('h3',`${date(item.fromDate)} → ${date(item.toDate)}`),text('span',labels[item.status] || item.status,'status '+item.status));
    card.append(row,text('p',item.reason),text('small',item.id));
    $('request-list').append(card);
  }
}
async function refresh() {
  clearTimeout(timer); if(refreshing) return; refreshing=true;
  try {
    const items=await api('/api/leave-requests');
    renderRequests(items);
    if(items.some(i=>i.status==='PENDING')) timer=setTimeout(refresh,2000);
  } catch(e) { notice('Không tải được dữ liệu. Kiểm tra ứng dụng rồi bấm Làm mới.',true); }
  finally { refreshing=false; }
}
$('leave-form').onsubmit=async event=>{
  event.preventDefault(); $('submit').disabled=true;
  try {
    const data=Object.fromEntries(new FormData(event.target));
    if (data.fromDate >= data.toDate) {
      notice('Ngày kết thúc phải sau ngày bắt đầu.',true);
      return;
    }
    await api('/api/leave-requests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    event.target.elements.reason.value=''; notice('Đã lưu yêu cầu. Bạn có thể theo dõi trạng thái bên cạnh.'); await refresh();
  } catch(e){notice(e.message,true);} finally{$('submit').disabled=false;}
};
$('refresh').onclick=refresh;
function isoDate(value) { return [value.getFullYear(),String(value.getMonth()+1).padStart(2,'0'),String(value.getDate()).padStart(2,'0')].join('-'); }
function minimumEndDate() {
  const start=new Date(`${$('from-date').value}T00:00:00`);
  start.setDate(start.getDate()+1);
  return isoDate(start);
}
const tomorrow=new Date();tomorrow.setDate(tomorrow.getDate()+1);const nextDay=new Date(tomorrow);nextDay.setDate(nextDay.getDate()+1);
$('from-date').value=isoDate(tomorrow);$('to-date').value=isoDate(nextDay);$('to-date').min=minimumEndDate();
$('from-date').onchange=()=>{const minimum=minimumEndDate();$('to-date').min=minimum;if($('to-date').value<minimum)$('to-date').value=minimum;};
async function initialize() {
  try {
    const config=await api('/api/config');
    $('connection-label').textContent=config.discordConfigured?'Discord đã được cấu hình':'Chưa cấu hình Discord';
    $('connection-dot').style.background=config.discordConfigured?'#5c9871':'#dca946';
    await refresh();
  } catch(e) {
    $('connection-label').textContent='Không tải được cấu hình';
    notice('Không thể đăng nhập API. Hãy tải lại trang và nhập đúng tài khoản.',true);
  }
}
initialize();
