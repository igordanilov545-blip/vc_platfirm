/* Проверяет живой Django в отдельной тестовой БД. Ничего не устанавливает. */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {chromium} = require(process.env.VC_PLAYWRIGHT_PACKAGE);
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
const assert = (ok, message) => { if (!ok) throw new Error(message); };
const output = process.env.VC_APPEARANCE_PREVIEWS || path.join(os.tmpdir(), 'vc-appearance-previews');
fs.mkdirSync(output, {recursive: true});
(async () => {
  const browser = await chromium.launch({headless: true});
  const errors = [];
  let checks = 0;
  try {
    const context = await browser.newContext({viewport: {width:1440,height:1000}, colorScheme:'light'});
    await context.addInitScript(ids => {
      localStorage.setItem('theme', 'dark'); // Чужая старая тема не управляет аккаунтом.
      localStorage.setItem('companion_settings_seen', '1');
      ids.forEach(id => localStorage.setItem('companion_tour_seen_u' + id, '1'));
    }, config.sessions.map(s => s.id));
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
      if (response.status() >= 400 && new URL(response.url()).pathname.startsWith('/static/'))
        errors.push('Static ' + response.status() + ': ' + response.url());
    });
    async function login(session) {
      await context.clearCookies();
      await context.addCookies([{name:config.cookieName,value:session.cookie,url:config.origin}]);
    }
    async function choose(appearance, theme) {
      await page.goto(config.origin + '/settings/?tab=appearance');
      await page.locator(`input[name="appearance"][value="${appearance}"]`).check();
      await page.locator(`input[name="color_theme"][value="${theme}"]`).check();
      await Promise.all([page.waitForNavigation(),page.locator('.appearance-save button').click()]);
      assert(await page.locator('html').getAttribute('data-appearance') === appearance, 'Appearance did not persist');
      assert(await page.locator('html').getAttribute('data-color-theme') === theme, 'Theme did not persist');
    }
    await login(config.sessions[0]);
    await page.goto(config.origin + '/settings/');
    assert(await page.locator('html').getAttribute('data-appearance') === 'nexus','Default must stay Nexus');
    assert(await page.locator('html').getAttribute('data-theme') === 'light','Legacy browser theme leaked into account');
    for (const theme of ['light','dark']) {
      await choose('minecraft', theme);
      for (const width of [1440,768,390,320]) {
        await page.setViewportSize({width,height:1000});
        for (const route of ['/', '/events/', config.sessions[0].profile, '/settings/?tab=appearance']) {
          const response = await page.goto(config.origin + route);
          assert(response.ok(), `HTTP ${response.status()} ${route} ${theme} ${width}`);
          const state = await page.evaluate(() => ({
            width:innerWidth, scroll:document.documentElement.scrollWidth,
            broken:[...document.images].filter(i=>i.getAttribute('src')&&i.complete&&!i.naturalWidth).map(i=>i.src),
            theme:document.documentElement.dataset.theme,
            owner:document.documentElement.dataset.appearanceOwner,
            ids:[...document.querySelectorAll('[id]')].map(e=>e.id)
          }));
          assert(state.owner === String(config.sessions[0].id), `Session lost: ${route} ${theme} ${width}; URL ${page.url()}`);
          assert(state.scroll <= state.width + 1, `Overflow ${route} ${theme} ${width}: ${state.scroll}`);
          assert(!state.broken.length, 'Broken images: ' + state.broken);
          assert(state.theme === theme, 'Theme changed on navigation');
          assert(new Set(state.ids).size === state.ids.length, 'Duplicate IDs ' + route);
          checks++;
          if ((width===1440||width===390)&&route==='/')
            await page.screenshot({path:path.join(output,`dashboard-${theme}-${width}.png`),fullPage:true});
          if (width===1440&&route.includes('?tab='))
            await page.screenshot({path:path.join(output,`settings-${theme}.png`),fullPage:true});
        }
      }
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.goto(config.origin + '/settings/?tab=appearance');
    await page.locator('#theme-toggle').click();
    await page.waitForFunction(() => !document.getElementById('theme-toggle').disabled);
    await page.reload();
    assert(await page.locator('html').getAttribute('data-theme') === 'light','Sidebar toggle was not saved');
    await page.route('**/settings/appearance/', route => route.abort());
    await page.locator('#theme-toggle').click();
    await page.locator('#appearance-notice').waitFor({state:'visible'});
    assert(await page.locator('html').getAttribute('data-theme') === 'light','Failed save did not roll back');
    await page.unroute('**/settings/appearance/');
    await page.setViewportSize({width:390,height:844});
    await page.locator('#more-tab-btn').click();
    assert(await page.locator('#more-tab-btn').getAttribute('aria-expanded') === 'true','Mobile menu');
    await page.locator('#more-theme-toggle').click();
    await page.waitForFunction(() => !document.getElementById('more-theme-toggle').disabled);
    await page.reload();
    assert(await page.locator('html').getAttribute('data-theme') === 'dark','Mobile toggle was not saved');
    await choose('minecraft','system');
    await page.emulateMedia({colorScheme:'light'});
    assert(await page.locator('html').getAttribute('data-theme') === 'light','System light');
    await page.emulateMedia({colorScheme:'dark'});
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await page.setViewportSize({width:1440,height:1000});
    await login(config.sessions[1]);
    await page.goto(config.origin + '/settings/?tab=appearance');
    assert(await page.locator('html').getAttribute('data-appearance') === 'nexus','Account isolation failed');
    await choose('minecraft','dark');
    await page.goto(config.origin + '/events/');
    await page.locator('[data-modal]').first().click();
    await page.locator('#modal-backdrop').waitFor({state:'visible'});
    await page.locator('#modal-body form').waitFor();
    const visible = await page.locator('#modal-close').evaluate(el => {
      const r=el.getBoundingClientRect();
      return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));
    });
    assert(visible,'Foreground covers the modal');
    await page.locator('#modal-close').click();
    await page.locator('#modal-backdrop').waitFor({state:'hidden'});
    await choose('nexus','light');
    assert(await page.locator('.mc-world').count() === 0, 'Minecraft decoration remains in Nexus');
    assert(await page.locator('link[href*="/appearances/minecraft"]').count() === 0,'Minecraft CSS remains in Nexus');
    assert(!errors.length, errors.join('\n'));
    console.log(`${checks} page/theme/viewport checks; save, reload, account isolation, desktop/mobile toggles, rollback, system theme, modal and Nexus return OK. Previews: ${output}`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
