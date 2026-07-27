const RETENTION_SECONDS = 90 * 86400;
const BATCH_SIZE = 1000;
const MAX_BATCHES = 5;

export async function cleanupExpired(db, nowSeconds = Math.floor(Date.now() / 1000)) {
  const cutoff = nowSeconds - RETENTION_SECONDS;
  let deleted = 0;
  for (let batch = 0; batch < MAX_BATCHES; batch += 1) {
    const result = await db.prepare(
      `DELETE FROM affiliate_clicks
        WHERE click_id IN (
          SELECT click_id FROM affiliate_clicks
           WHERE created_at < ?1
           ORDER BY created_at ASC, click_id ASC
           LIMIT ?2
        )`,
    ).bind(cutoff, BATCH_SIZE).run();
    const changes = Number(result?.meta?.changes || 0);
    deleted += changes;
    if (changes < BATCH_SIZE) break;
  }
  return { deleted, cutoff, max_batches: MAX_BATCHES, batch_size: BATCH_SIZE };
}

export default {
  async scheduled(_event, env) {
    return cleanupExpired(env.DB);
  },
};
