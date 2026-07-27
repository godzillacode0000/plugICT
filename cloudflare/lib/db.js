export async function findActiveAffiliate(db, code) {
  return db.prepare(
    `SELECT code, display_name
       FROM affiliate_codes
      WHERE code = ?1 AND status = 'active'
      LIMIT 1`,
  ).bind(code).first();
}

export async function insertClick(db, event, visitorHash, nowSeconds = Math.floor(Date.now() / 1000)) {
  const day = new Date(nowSeconds * 1000).toISOString().slice(0, 10);
  const result = await db.prepare(
    `INSERT OR IGNORE INTO affiliate_clicks
      (click_id, affiliate_code, visitor_hash, path, referrer_host, day, created_at)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)`,
  ).bind(
    event.click_id,
    event.code,
    visitorHash,
    event.path,
    event.referrer_host,
    day,
    nowSeconds,
  ).run();
  return Number(result?.meta?.changes || 0) === 1;
}

export async function getAffiliateStats(db, code, sinceSeconds) {
  const row = await db.prepare(
    `SELECT COUNT(*) AS clicks,
            COUNT(DISTINCT visitor_hash) AS unique_clicks
       FROM affiliate_clicks
      WHERE affiliate_code = ?1 AND created_at >= ?2`,
  ).bind(code, sinceSeconds).first();
  const clicks = Number(row?.clicks || 0);
  const uniqueClicks = Number(row?.unique_clicks || 0);
  return {
    clicks,
    unique_clicks: uniqueClicks,
    purchases: null,
    conversion_rate: null,
    pending_commission_cents: null,
    paid_commission_cents: null,
    voided_purchases: null,
    finance_status: 'not_connected',
  };
}
