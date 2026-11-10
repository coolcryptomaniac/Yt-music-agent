import test from 'node:test';
import assert from 'node:assert/strict';
import {dailyCreativeBriefs,CAMPAIGNS} from '../src/creative.js';

test('four distinct creative lanes and original prompts',()=>{
  assert.equal(CAMPAIGNS.length,4);
  assert.equal(new Set(CAMPAIGNS.map(x=>x.title)).size,4);
  for(const c of CAMPAIGNS) {
    assert.ok(c.music.length>100 && c.video.length>100);
    assert.ok(!/Suno password|CAPTCHA bypass|existing melody copy/i.test(c.music));
  }
});
test('two-hour repeat is idempotent and does not spend credits',()=>{
  const first=dailyCreativeBriefs('2026-11-11',1);
  const second=dailyCreativeBriefs('2026-11-11',1);
  assert.deepEqual(first,second);
  assert.equal(first[0].status,'idea');
  assert.equal(first[0].estimated_new_generation_cost_usd,0);
});
test('bounded planning and different day rotates',()=>{
  assert.equal(dailyCreativeBriefs('2026-11-11',99).length,2);
  assert.notEqual(dailyCreativeBriefs('2026-11-11',1)[0].campaign_id,dailyCreativeBriefs('2026-11-12',1)[0].campaign_id);
});
