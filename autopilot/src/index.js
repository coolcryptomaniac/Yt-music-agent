/*
 * Vusic music-career autopilot: conservative, verified, account-authorized automation.
 * No browser automation, CAPTCHA evasion, cookies, passwords, synthetic streams,
 * mass engagement, or unapproved production publishing.
 */
const JSON_HEADERS = { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' };
const MAX_RECORDS = 200;
const YT_API = 'https://www.googleapis.com/youtube/v3';
function reply(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
}
function fail(message, status = 400) { return reply({ error: message }, status); }
function integerMoney(value, field) {
  if (!/^\d+(?:\.\d{1,3})?$/.test(String(value))) throw new Error(field + ': nonnegative INR amount required');
  const result = Math.round(Number(value) * 100);
  if (!Number.isSafeInteger(result)) throw new Error(field + ': outside supported range');
  return result;
}
function checkDate(v) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(v)) || Number.isNaN(Date.parse(v + 'T00:00:00Z'))) {
    throw new Error('Invalid ISO payment date');
  }
  return String(v);
}
function clean(v, length = 250) { return String(v || '').trim().slice(0, length); }
async function authorized(request, secret) {
  if (!secret) return false;
  const value = request.headers.get('Authorization') || '';
  const expected = 'Bearer ' + secret;
  const hash = async s => new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)));
  const [a, b] = await Promise.all([hash(value), hash(expected)]);
  let difference = 0;
  for (let i = 0; i < a.length; i++) difference |= a[i] ^ b[i];
  return difference === 0;
}
async function jsonBody(request) {
  const contentLength = Number(request.headers.get('content-length') || 0);
  if (contentLength > 1024 * 1024) throw new Error('Body too large');
  return request.json();
}
async function flag(env, id, category, severity, explanation) {
  await env.DB.prepare('INSERT OR IGNORE INTO audit_flags (id,category,severity,explanation) VALUES (?,?,?,?)')
    .bind(id,category,severity,explanation).run();
}
async function ingestPayouts(request, env) {
  const data = await jsonBody(request);
  if (!Array.isArray(data.records) || data.records.length === 0 || data.records.length > MAX_RECORDS) throw new Error('records must contain 1 to 200 payouts');
  let added = 0;
  for (const item of data.records) {
    const date = checkDate(item.payment_date);
    const id = clean(item.id || date, 100);
    const gross = integerMoney(item.royalty, 'royalty');
    const tax = integerMoney(item.tds, 'tds');
    const net = integerMoney(item.net, 'net');
    if (tax > gross) throw new Error(id + ': TDS exceeds royalty');
    await env.DB.prepare('INSERT INTO payouts (id,payment_date,gross_paise,tds_paise,net_paise,transaction_reference) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payment_date=excluded.payment_date,gross_paise=excluded.gross_paise,tds_paise=excluded.tds_paise,net_paise=excluded.net_paise,transaction_reference=excluded.transaction_reference')
      .bind(id,date,gross,tax,net,clean(item.transaction_reference,120) || null).run();
    added++;
    if (Math.abs(gross - tax - net) > 1) await flag(env,'payout-mismatch:' + id,'arithmetic','high','Reported payout does not equal gross royalty minus TDS for ' + date);
    const taxRatio = gross ? tax / gross : 0;
    if (gross && (taxRatio < 0.08 || taxRatio > 0.12)) {
      await flag(env,'tds-review:' + id,'tax','review','Unusual withholding fraction ' + (100*taxRatio).toFixed(2) + '% on ' + date + '; verify applicable law and TDS statement, not proof of fraud.');
    }
  }
  return reply({ imported:added, note:'Records do not prove cash was received; verify bank credits separately.' });
}
async function ingestRoyalties(request, env) {
  const data = await jsonBody(request);
  if (!Array.isArray(data.records) || data.records.length < 1 || data.records.length > MAX_RECORDS) throw new Error('records must contain 1 to 200 royalty lines');
  for (const line of data.records) {
    const id=clean(line.id,120), period=clean(line.period,15), platform=clean(line.platform,80);
    if (!id || !/^\d{4}-\d{2}$/.test(period) || !platform) throw new Error('Each line requires stable id, YYYY-MM period and platform');
    const gross = line.platform_gross == null ? null : integerMoney(line.platform_gross,'platform_gross');
    const reported = line.artist_reported == null ? null : integerMoney(line.artist_reported,'artist_reported');
    const streams = line.streams == null ? null : Number(line.streams);
    if (streams !== null && (!Number.isSafeInteger(streams) || streams < 0)) throw new Error('Invalid stream count');
    await env.DB.prepare('INSERT INTO royalty_lines (id,period,platform,isrc,title,streams,platform_gross_paise,artist_reported_paise,source) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET streams=excluded.streams,platform_gross_paise=excluded.platform_gross_paise,artist_reported_paise=excluded.artist_reported_paise,source=excluded.source')
      .bind(id,period,platform,clean(line.isrc,25) || null,clean(line.title,160) || null,streams,gross,reported,clean(line.source,120) || 'vusic-export').run();
  }
  // Indicative share audit only when the account owner explicitly configures signed rates.
  const lines = data.records;
  let shareReviewed = 0;
  for (const line of lines) {
    if (line.platform_gross == null || line.artist_reported == null) continue;
    const channel = String(line.platform || '');
    const rateString = /youtube.*(ugc|content.?id)/i.test(channel) ? env.CONTRACT_SHARE_CONTENT_ID : env.CONTRACT_SHARE_STREAMING;
    if (!rateString) continue;
    const share = Number(rateString);
    if (!(share > 0 && share <= 1)) throw new Error('Contract share must be decimal 0 to 1');
    const gross = integerMoney(line.platform_gross,'platform_gross');
    const reported = integerMoney(line.artist_reported,'artist_reported');
    const expected = Math.round(gross * share);
    shareReviewed++;
    if (Math.abs(reported - expected) > Math.max(100, Math.round(gross * 0.025))) {
      await flag(env,'share-check:' + clean(line.id,120),'contract-share','review',
        'Reported artist royalty for ' + clean(line.id,100) + ' differs from nominal contract share. Confirm whether gross is pre-commission, currency FX, taxes, platform corrections, and the correct signed terms.');
    }
  }
  return reply({ imported:data.records.length, share_reviewed:shareReviewed, note:'Share checks are provisional and apply only with owner-configured contract rates; not proof of underpayment.' });
}
async function audit(env) {
  const p = await env.DB.prepare('SELECT count(*) count,coalesce(sum(gross_paise),0) gross,coalesce(sum(tds_paise),0) tds,coalesce(sum(net_paise),0) net,coalesce(sum(bank_verified),0) bank_verified FROM payouts').first();
  const r = await env.DB.prepare('SELECT count(*) count,coalesce(sum(artist_reported_paise),0) artist_reported FROM royalty_lines').first();
  const f = await env.DB.prepare('SELECT id,category,severity,explanation,created_at FROM audit_flags WHERE resolved_at IS NULL ORDER BY created_at DESC LIMIT 40').all();
  return reply({ currency:'INR', payout_count:p.count, gross_paise:p.gross, tds_paise:p.tds, net_paise:p.net, cash_confirmed_count:p.bank_verified, royalty_lines:r.count, royalty_reported_paise:r.artist_reported, flags:f.results, caution:'Deductions matched is NOT evidence all DSP royalties are accounted for.' });
}
async function addToQueue(request,env) {
  const x=await jsonBody(request), platform=clean(x.platform,20);
  if (!['instagram','youtube'].includes(platform)) throw new Error('platform must be instagram or youtube');
  const title=clean(x.title,90), caption=clean(x.caption,2100);
  const id=crypto.randomUUID(), when=clean(x.scheduled_at,50);
  if (!title || !when || Number.isNaN(Date.parse(when))) throw new Error('title and ISO scheduled_at required');
  const media=clean(x.media_url,1200), r2=clean(x.r2_key,300);
  if (platform==='instagram' && (!media.startsWith('https://') || !new URL(media).hostname)) throw new Error('Instagram needs an HTTPS public video URL');
  if (platform==='youtube' && (!r2 || r2.startsWith('/') || r2.includes('..'))) throw new Error('YouTube needs an R2 video object key');
  await env.DB.prepare("INSERT INTO publish_queue (id,platform,title,caption,media_url,r2_key,scheduled_at) VALUES (?,?,?,?,?,?,?)")
    .bind(id,platform,title,caption,media || null,r2 || null,when).run();
  return reply({ id,status:'draft',note:'Review rights, content and metadata, then explicitly approve.' },201);
}
async function approve(request,env,id) {
  const data=await jsonBody(request);
  if (data.rights_verified !== true || !clean(data.approved_by,100)) throw new Error('Explicit rights_verified:true and approved_by are required');
  const res=await env.DB.prepare("UPDATE publish_queue SET rights_verified=1,approved_by=?,status='approved',updated_at=datetime('now') WHERE id=? AND status='draft'")
    .bind(clean(data.approved_by,100),id).run();
  return reply({ approved:res.meta.changes===1,live_publishing_enabled:env.AUTO_PUBLISH==='true' });
}
async function addRun(env,task,status,notes='') {
  await env.DB.prepare('INSERT INTO autopilot_runs (task,status,notes) VALUES (?,?,?)').bind(task,status,clean(notes,500)).run();
}
async function discoverTrends(env) {
  if (!env.YOUTUBE_API_KEY) return addRun(env,'trends','skipped','YOUTUBE_API_KEY not configured');
  const queries=(env.TREND_TERMS || 'Kumaoni music,Himalayan electronic music').split(',').map(s=>s.trim()).filter(Boolean).slice(0,3);
  let count=0;
  for (const query of queries) {
    const params=new URLSearchParams({part:'snippet',type:'video',maxResults:'5',order:'viewCount',publishedAfter:new Date(Date.now()-14*86400000).toISOString(),q:query,key:env.YOUTUBE_API_KEY});
    const res=await fetch(YT_API + '/search?' + params);
    if (!res.ok) throw new Error('YouTube trends API: ' + res.status);
    for (const row of (await res.json()).items || []) {
      const id=clean(row.id && row.id.videoId,90);
      if (!id) continue;
      await env.DB.prepare('INSERT INTO observed_videos (id,topic,title,channel,published_at) VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,channel=excluded.channel')
        .bind(id,query,clean(row.snippet.title,240),clean(row.snippet.channelTitle,160),row.snippet.publishedAt || null).run();
      count++;
    }
  }
  if (env.YOUTUBE_CHANNEL_ID) {
    const url=YT_API + '/channels?' + new URLSearchParams({part:'statistics',id:env.YOUTUBE_CHANNEL_ID,key:env.YOUTUBE_API_KEY});
    const res=await fetch(url);
    if (res.ok) {
      const data=await res.json(), stats=data.items && data.items[0] && data.items[0].statistics;
      if (stats) await env.DB.prepare('INSERT INTO channel_snapshots (subscribers,views,videos) VALUES (?,?,?)')
        .bind(Number(stats.subscriberCount || 0),Number(stats.viewCount || 0),Number(stats.videoCount || 0)).run();
    }
  }
  await addRun(env,'trends','ok',count+' observed relevant videos');
}
async function instagramCreate(env,job) {
  if (!env.INSTAGRAM_USER_ID || !env.META_ACCESS_TOKEN) throw new Error('Instagram OAuth token and professional account ID required');
  const base='https://graph.facebook.com/' + (env.META_GRAPH_VERSION || 'v25.0');
  const body=new URLSearchParams({media_type:'REELS',video_url:job.media_url,caption:job.caption,share_to_feed:'true',access_token:env.META_ACCESS_TOKEN});
  const res=await fetch(base + '/' + encodeURIComponent(env.INSTAGRAM_USER_ID) + '/media',{method:'POST',body});
  const data=await res.json();
  if (!res.ok || !data.id) throw new Error('Instagram container creation failed: ' + res.status + ' ' + clean(data.error && data.error.message,200));
  await env.DB.prepare("UPDATE publish_queue SET status='staged',provider_job_id=?,updated_at=datetime('now') WHERE id=?")
    .bind(String(data.id),job.id).run();
}
async function instagramFinalize(env,job) {
  const base='https://graph.facebook.com/' + (env.META_GRAPH_VERSION || 'v25.0');
  const statusResp=await fetch(base + '/' + encodeURIComponent(job.provider_job_id) + '?' + new URLSearchParams({fields:'status_code',access_token:env.META_ACCESS_TOKEN}));
  if (!statusResp.ok) throw new Error('Instagram processing status: ' + statusResp.status);
  const state=(await statusResp.json()).status_code;
  if (state==='ERROR' || state==='EXPIRED') throw new Error('Instagram media processing: ' + state);
  if (state!=='FINISHED') return;
  // Mark attempted BEFORE external side effect, so an uncertain response never retries/post duplicates.
  await env.DB.prepare("UPDATE publish_queue SET status='publish_attempted',updated_at=datetime('now') WHERE id=? AND status='staged'").bind(job.id).run();
  const body=new URLSearchParams({creation_id:job.provider_job_id,access_token:env.META_ACCESS_TOKEN});
  const response=await fetch(base + '/' + encodeURIComponent(env.INSTAGRAM_USER_ID) + '/media_publish',{method:'POST',body});
  const data=await response.json();
  if (!response.ok || !data.id) throw new Error('Instagram publish ambiguous; verify manually: '+clean(data.error && data.error.message,200));
  await env.DB.prepare("UPDATE publish_queue SET status='published',provider_post_id=?,updated_at=datetime('now') WHERE id=?")
    .bind(String(data.id),job.id).run();
}
async function youtubeUpload(env,job) {
  if (!env.YOUTUBE_REFRESH_TOKEN || !env.YOUTUBE_CLIENT_ID || !env.YOUTUBE_CLIENT_SECRET) throw new Error('Google OAuth credentials missing');
  const video=await env.VIDEOS.get(job.r2_key);
  if (!video) throw new Error('Video object not found in R2');
  const tokenBody=new URLSearchParams({client_id:env.YOUTUBE_CLIENT_ID,client_secret:env.YOUTUBE_CLIENT_SECRET,refresh_token:env.YOUTUBE_REFRESH_TOKEN,grant_type:'refresh_token'});
  const tokens=await fetch('https://oauth2.googleapis.com/token',{method:'POST',body:tokenBody});
  if (!tokens.ok) throw new Error('Google OAuth refresh failed: ' + tokens.status);
  const bearer=(await tokens.json()).access_token;
  if (!bearer) throw new Error('Google OAuth did not supply access token');
  const metadata={snippet:{title:job.title,description:job.caption,categoryId:'10'},status:{privacyStatus:'private',selfDeclaredMadeForKids:false}};
  const init=await fetch('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',{method:'POST',headers:{Authorization:'Bearer '+bearer,'Content-Type':'application/json; charset=UTF-8','X-Upload-Content-Type':'video/mp4','X-Upload-Content-Length':String(video.size)},body:JSON.stringify(metadata)});
  if (!init.ok) throw new Error('YouTube upload session failed: '+init.status);
  const location=init.headers.get('location');
  if (!location || !location.startsWith('https://')) throw new Error('YouTube resumable upload session missing');
  // No retry after this step without a human audit: the video may exist even after a timeout.
  await env.DB.prepare("UPDATE publish_queue SET status='publish_attempted',updated_at=datetime('now') WHERE id=?").bind(job.id).run();
  const uploaded=await fetch(location,{method:'PUT',headers:{'Content-Type':'video/mp4','Content-Length':String(video.size)},body:video.body});
  const response=await uploaded.json().catch(()=>({}));
  if (!uploaded.ok || !response.id) throw new Error('YouTube upload ambiguous; inspect Studio before retrying: '+uploaded.status);
  await env.DB.prepare("UPDATE publish_queue SET status='published_private',provider_post_id=?,updated_at=datetime('now') WHERE id=?")
    .bind(String(response.id),job.id).run();
}
async function publishingCycle(env) {
  if (env.AUTO_PUBLISH !== 'true') return addRun(env,'publishing','disabled','Set AUTO_PUBLISH=true only after linking OAuth accounts and media');
  const rows=await env.DB.prepare("SELECT * FROM publish_queue WHERE ((status='approved' AND scheduled_at<=?) OR status='staged') ORDER BY scheduled_at LIMIT 4")
    .bind(new Date().toISOString()).all();
  for (const item of rows.results) {
    try {
      if (!item.rights_verified || !item.approved_by) throw new Error('Missing human rights approval');
      if (item.status==='staged') {
        await instagramFinalize(env,item);
      } else {
        const lock=await env.DB.prepare("UPDATE publish_queue SET status='processing',updated_at=datetime('now') WHERE id=? AND status='approved'").bind(item.id).run();
        if (lock.meta.changes!==1) continue;
        if (item.platform==='instagram') await instagramCreate(env,item);
        else await youtubeUpload(env,item);
      }
    } catch (error) {
      // Failed external API calls can be ambiguous; a human must check before any retry.
      await env.DB.prepare("UPDATE publish_queue SET status='needs_review',last_error=?,updated_at=datetime('now') WHERE id=?")
        .bind(clean(error.message,500),item.id).run();
    }
  }
  await addRun(env,'publishing','ok',String(rows.results.length)+' queued items inspected');
}
export default {
  async fetch(request,env) {
    try {
      const url=new URL(request.url);
      if (url.pathname==='/health' && request.method==='GET') return reply({status:'ok',version:'1.0',automation_every_hours:2,publishing_enabled:env.AUTO_PUBLISH==='true'});
      if (!await authorized(request,env.ADMIN_TOKEN)) return fail('Unauthorized',401);
      if (url.pathname==='/ingest/payouts' && request.method==='POST') return await ingestPayouts(request,env);
      if (url.pathname==='/ingest/royalties' && request.method==='POST') return await ingestRoyalties(request,env);
      const bankMatch=url.pathname.match(/^\/payouts\/([a-zA-Z0-9_.:-]+)\/verify-bank$/);
      if (bankMatch && request.method==='POST') {
        const data=await jsonBody(request);
        if (data.receipt_confirmed !== true) throw new Error('Manually confirm bank credit before verification');
        const result=await env.DB.prepare('UPDATE payouts SET bank_verified=1 WHERE id=?').bind(bankMatch[1]).run();
        return reply({verified:result.meta.changes===1});
      }
      if (url.pathname==='/audit' && request.method==='GET') return await audit(env);
      if (url.pathname==='/trends' && request.method==='GET') {
        const result=await env.DB.prepare('SELECT topic,title,channel,published_at,captured_at FROM observed_videos ORDER BY captured_at DESC LIMIT 60').all();
        return reply(result.results);
      }
      if (url.pathname==='/queue' && request.method==='GET') {
        const result=await env.DB.prepare('SELECT id,platform,title,scheduled_at,status,provider_post_id,last_error FROM publish_queue ORDER BY created_at DESC LIMIT 100').all();
        return reply(result.results);
      }
      if (url.pathname==='/queue' && request.method==='POST') return await addToQueue(request,env);
      const approveMatch=url.pathname.match(/^\/queue\/([0-9a-f-]+)\/approve$/);
      if (approveMatch && request.method==='POST') return await approve(request,env,approveMatch[1]);
      return fail('Not found',404);
    } catch (error) { return fail(clean(error.message,500),400); }
  },
  async scheduled(controller,env,ctx) {
    ctx.waitUntil((async()=>{
      try { await discoverTrends(env); } catch(e) { await addRun(env,'trends','failed',e.message); }
      try { await publishingCycle(env); } catch(e) { await addRun(env,'publishing','failed',e.message); }
    })());
  }
};
