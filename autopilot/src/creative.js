/*
 * Original music and video briefs. Broad genre ingredients, not impersonations of
 * contemporary artists or reconstructions of protected compositions.
 * Never publishes, spends Suno credits or uploads automatically.
 */
export const CAMPAIGNS = Object.freeze([
  {
    id: 'valley-remembers',
    title: 'The Valley Remembers',
    lane: 'Himalayan ethereal / ambient folk',
    bpm: 72,
    music: 'Original ethereal cinematic ambient folk, 72 BPM, D minor, layered wordless female vocal harmonies without imitation of any known singer, Celtic harp, Himalayan bamboo flute, distant warm strings, subtle frame drum, natural mountain reverb, intimate verse growing into luminous orchestral chorus, beautiful original memorable four-note motif, nuanced dynamics, warm mastering, 3m30s. No sampled recordings or existing melodies.',
    video: 'Original Himalayan fantasy world: misty cedar forest, secluded mountain lake, ancient stone shrine, glowing Aipan-inspired hand-drawn patterns, lone traveler encounters a benevolent starlight spirit. Wide establishing shots, intimate detail, warm sunrise finale, gentle realistic camera movement, consistent character and world, no existing characters or franchise elements, no on-screen lyrics.',
    hooks: ['A lost melody wakes an ancient valley','One light can bring the mountain home']
  },
  {
    id: 'ghosts-in-the-rain',
    title: 'Ghosts in the Rain',
    lane: 'Atmospheric future garage / electronic',
    bpm: 132,
    music: 'Original underground future garage, 132 BPM, F minor, shuffled syncopated 2-step drums, irregular ghost snares, warm sub bass, nonverbal chopped vocal textures, rain ambience, granular echoes, detuned pads, sparse haunting original four-note melody, emotional bass drop at 45 seconds, cinematic mix with wide spatial ambience. No unauthorized samples, no recognizable artist voices.',
    video: 'Original nocturnal science-fiction story: lone protagonist walks through empty rain-soaked subway station and finds reflections moving independently. Reality breaks subtly on bass hits; neon tunnels fragment into surreal alternate city, melancholy but hopeful ending, photoreal cinematic lighting, consistent protagonist and clothing, purposeful motion, no existing fictional franchise or logos.',
    hooks: ['The last train never stopped','Rain remembers the city']
  },
  {
    id: 'world-made-of-snow',
    title: 'A World Made of Snow',
    lane: 'Game ambient / nostalgic piano',
    bpm: 78,
    music: 'Original minimalist atmospheric game soundtrack, 78 BPM, G major with emotional relative minor movement, felt piano original six-note hook, analog synth pads, subtle 8-bit bell accents, mellow vibraphone, restrained tape hiss, soft orchestral swells, nostalgic winter ambience, gentle evolving arrangement, seamless loop-friendly outro, instrumental, 3 minutes.',
    video: 'Original pixel-art fantasy adventure: small cloaked traveler crosses snowy pine forest, warm cabin, quiet abandoned village and blue crystal caves before awakening a magical tree. Cohesive 16-bit-inspired pixel art, layered parallax, warm lanterns against blue snow, smooth motion, final sunrise, no recognizable game characters or copyrighted levels, no logos.',
    hooks: ['A forgotten world remembers you','This snow has a story']
  },
  {
    id: 'where-stars-sleep',
    title: 'Where the Stars Sleep',
    lane: 'Dreamy winter ambient / downtempo electronic',
    bpm: 66,
    music: 'Original minimal dreamlike ambient electronic instrumental, 66 BPM, A minor, spacious shimmering synths, soft felt piano, gently detuned analog chords, airy pads, distant bells, reversed textures, quiet pulsing bass, haunting original five-note motif within first ten seconds, intimate melancholy, delicate granulation, warm cinematic reverb, 3m20s. No melody copying.',
    video: 'Original winter cosmic reverie: solitary traveler in snow-covered forest follows a tiny falling star across an icy lake; reflection becomes glowing constellations, camera slowly rises to a galaxy above distant mountains, restrained indigo/cyan palette, photoreal fog, careful elegant long transitions, single coherent emotional story, no visual text or logos.',
    hooks: ['Some stars fall to guide us','The quietest place in the universe']
  }
]);

export function dailyCreativeBriefs(utcDate, maxCount = 1) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(utcDate)) throw new Error('Expected UTC YYYY-MM-DD');
  // Stable modulo shuffle: repeated 2-hour Worker invocations create no new
  // production ideas and cannot accidentally consume Suno credits.
  const day = Math.floor(Date.parse(utcDate + 'T00:00:00Z') / 86400000);
  const n = Math.max(1, Math.min(2, Math.floor(Number(maxCount) || 1)));
  return Array.from({length:n}, (_,i)=>{
    const c=CAMPAIGNS[(day + i*3) % CAMPAIGNS.length];
    return {
      id: utcDate + ':' + c.id,
      date:utcDate,
      campaign_id:c.id,
      title:c.title,
      lane:c.lane,
      bpm:c.bpm,
      music_prompt:c.music,
      video_prompt:c.video,
      hook:c.hooks[(Math.floor(day/4) + i) % c.hooks.length],
      short_format:'9:16, 1080x1920, 15-45 seconds, sound-on hook in first 2 seconds, beat-aware edits, music licensed, original footage',
      long_format:'16:9, 1920x1080, original story arc synced in editor to waveform/beat grid, separate thumbnail and subtitles where appropriate',
      status:'idea',
      estimated_new_generation_cost_usd:0
    };
  });
}
