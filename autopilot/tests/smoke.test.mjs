import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.js';

function mockDb() {
  const payouts = [];
  const flags = [];
  return {
    payouts,flags,
    prepare(sql) {
      let values = [];
      return {
        bind(...args) { values = args; return this; },
        async run() {
          if (sql.startsWith('INSERT INTO payouts')) payouts.push(values);
          if (sql.startsWith('INSERT OR IGNORE INTO audit_flags')) flags.push(values);
          return { meta:{changes:1} };
        },
        async first() { return {count:payouts.length,gross:10000,tds:1000,net:9000,bank_verified:0,artist_reported:0}; },
        async all() {return {results:[]};}
      };
    }
  };
}
const req=(path,method='GET',data,authorized=true) => new Request('https://autopilot.example'+path,{
  method,headers:authorized?{Authorization:'Bearer a-strong-test-token', 'Content-Type':'application/json'}:{},
  body:data?JSON.stringify(data):undefined
});
const env=db=>({ADMIN_TOKEN:'a-strong-test-token',DB:db,AUTO_PUBLISH:'false'});
test('health is public and does not expose credentials',async ()=>{
  const response=await worker.fetch(req('/health'),env(mockDb()));
  assert.equal(response.status,200);
  const json=await response.json();
  assert.equal(json.publishing_enabled,false);
  assert.equal(JSON.stringify(json).includes('strong-test-token'),false);
});
test('audit and imports require owner auth',async ()=>{
  const response=await worker.fetch(req('/audit','GET',undefined,false),env(mockDb()));
  assert.equal(response.status,401);
});
test('payout record import reconciles gross-TDS-net and stores private records in DB only',async ()=>{
  const db=mockDb();
  const response=await worker.fetch(req('/ingest/payouts','POST',{
    records:[{id:'sample-payout',payment_date:'2026-10-05',royalty:'100.00',tds:'10.00',net:'90.00'}]
  }),env(db));
  assert.equal(response.status,200,await response.text());
  assert.equal(db.payouts.length,1);
  assert.equal(db.payouts[0][2],10000);
  assert.equal(db.payouts[0][3],1000);
  assert.equal(db.payouts[0][4],9000);
  assert.equal(db.flags.length,0);
});
test('mismatching payout is flagged without accusing a distributor',async ()=>{
  const db=mockDb();
  const response=await worker.fetch(req('/ingest/payouts','POST',{
    records:[{id:'sample-mismatch',payment_date:'2026-09-05',royalty:'100.00',tds:'10.00',net:'89.00'}]
  }),env(db));
  assert.equal(response.status,200);
  assert.equal(db.flags[0][1],'arithmetic');
});
test('invalid payout numbers fail without writing',async ()=>{
  const db=mockDb();
  const response=await worker.fetch(req('/ingest/payouts','POST',{
    records:[{payment_date:'2026-09-05',royalty:'bad',tds:'10.00',net:'90.00'}]
  }),env(db));
  assert.equal(response.status,400);
  assert.equal(db.payouts.length,0);
});
