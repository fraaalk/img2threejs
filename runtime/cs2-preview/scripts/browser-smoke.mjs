import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('http://127.0.0.1:4173', { waitUntil: 'networkidle' });
  await page.locator('#state').waitFor({ state: 'visible' });
  for (const selector of ['#fixed-view', '#orbit-a', '#orbit-b']) await page.locator(selector).click();
  const result = await page.evaluate(() => {
    const artifact = window.__CS2_REVIEW_ARTIFACT__;
    return {
      title: document.title,
      state: document.querySelector('#state')?.textContent,
      coverage: document.querySelector('#coverage')?.textContent,
      artifact,
    };
  });
  if (errors.length > 0) throw new Error(`browser errors: ${errors.join('; ')}`);
  if (result.state !== 'state: proceed') throw new Error(`unexpected state: ${result.state}`);
  if (!result.title.includes('Hedge Maze')) throw new Error(`unexpected title: ${result.title}`);
  if (!result.artifact || result.artifact.projectionStatus !== 'fallback') throw new Error('glove preview must not report an unbaked projection as ready');
  if (result.artifact.projectionCoverage !== 0) throw new Error(`unbaked glove preview reported coverage: ${result.artifact.projectionCoverage}`);
  for (const label of ['fixed-view', 'orbit-a', 'orbit-b']) {
    if (!result.artifact.captures[label]?.startsWith('data:image/png')) throw new Error(`missing ${label} capture`);
  }
  if (result.artifact.family !== 'glove' || result.artifact.adapterId !== 'cs2-glove-v1') throw new Error('glove adapter artifact missing');
  if (result.artifact.materialChannels.join(',') !== 'albedo,roughness,normal,ao,wear-mask') throw new Error('independent glove material channels missing');
  const artifactLink = await page.locator('#download-artifact').getAttribute('href');
  if (!artifactLink?.startsWith('blob:')) throw new Error('review artifact download is not owned by the runtime');
  console.log(JSON.stringify({ smoke: 'pass', coverage: result.artifact.projectionCoverage, captures: Object.keys(result.artifact.captures) }));
} finally {
  await browser.close();
}
