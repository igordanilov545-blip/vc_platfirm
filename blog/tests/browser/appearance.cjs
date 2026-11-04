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
      await page.goto(config.origin + '/settings/');
      // В общей in-memory SQLite ждём завершения фоновой загрузки вкладки хаба
      // до следующей записи; в рабочей SQLite используется WAL и timeout.
      await page.waitForLoadState('networkidle');
      const pageOwner = await page.locator('html').getAttribute('data-appearance-owner');
      await page.locator('.appearance-launcher').click();
      await page.locator('#modal-body [data-appearance-form]').waitFor();
      await page.waitForLoadState('networkidle');
      assert(await page.locator('#modal-body button[type="submit"]').count() === 0, 'Unexpected confirmation button');
      if (await page.locator('html').getAttribute('data-appearance') !== appearance) {
        await Promise.all([page.waitForNavigation(),page.locator(`#modal-body input[name="appearance"][value="${appearance}"]`).check()]);
        assert(await page.locator('html').getAttribute('data-appearance-owner') === pageOwner, 'Account lost while updating appearance');
        await page.locator('#modal-body [data-appearance-form]').waitFor();
        await page.waitForLoadState('networkidle');
      }
      const radio = page.locator(`#modal-body input[name="color_theme"][value="${theme}"]`);
      if (!await radio.isChecked()) {
        await Promise.all([page.waitForResponse(r=>r.url().endsWith('/settings/appearance/')&&r.request().method()==='POST'),radio.check()]);
        await page.waitForFunction(()=>!document.querySelector('[data-appearance-form][data-saving]'));
      }
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
          if (route.includes('?tab=')) {
            await page.locator('#modal-body [data-appearance-form]').waitFor();
            const fits = await page.locator('#modal-body').evaluate(el => el.scrollWidth <= el.clientWidth + 1);
            assert(fits, `Appearance window overflows ${theme} ${width}`);
          }
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
          assert(await page.locator('.mc-world-image.mc-asset-' + theme).isVisible(), 'World asset missing');
          const frame = await page.locator('.stat-tile,.card:has(table),.personal-settings-card').first().evaluate(el => {
            const style = getComputedStyle(el);
            return {source:style.backgroundImage,repeat:style.backgroundRepeat,width:parseFloat(style.borderLeftWidth)};
          });
          assert(frame.source.includes('/frames_flat/')&&frame.repeat.includes('repeat-x')&&frame.repeat.includes('repeat-y')&&frame.width>0,'Frame is not modular: '+JSON.stringify(frame));
          assert(await page.locator('.mc-avatar').count() === 1, 'Account avatar missing');
          assert(new Set(state.ids).size === state.ids.length, 'Duplicate IDs ' + route);
          checks++;
          if ((width===1440||width===390)&&route==='/')
            await page.screenshot({path:path.join(output,`dashboard-${theme}-${width}.png`),fullPage:true,animations:'disabled'});
          if (width===1440&&route.includes('?tab='))
            await page.screenshot({path:path.join(output,`settings-${theme}.png`),fullPage:true,animations:'disabled'});
          if (width===390&&route.includes('?tab='))
            await page.screenshot({path:path.join(output,`settings-${theme}-390.png`),fullPage:true,animations:'disabled'});
        }
      }
    }
    await page.setViewportSize({width:1440,height:1000});
    await page.goto(config.origin + '/settings/');
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
    await page.route('**/settings/appearance/', route => route.abort());
    await page.locator('#modal-body input[name="color_theme"][value="light"]').click();
    await page.locator('[data-appearance-status][data-error]').waitFor();
    assert(await page.locator('#modal-body input[name="color_theme"][value="system"]').isChecked(), 'Modal theme did not roll back');
    await page.locator('#modal-body input[name="appearance"][value="nexus"]').click();
    await page.waitForFunction(() => !document.querySelector('[data-appearance-form][data-saving]'));
    assert(await page.locator('#modal-body input[name="appearance"][value="minecraft"]').isChecked(), 'Modal appearance did not roll back');
    await page.unroute('**/settings/appearance/');
    // Не только наличие атласа: меняем длину и высоту живой панели, толщина
    // углов остаётся постоянной для всех шести вариантов материала.
    await page.setViewportSize({width:1800,height:1100});
    await page.goto(config.origin + '/');
    const variants = await page.evaluate(() => {
      const panel = document.createElement('section');
      panel.className = 'card';
      panel.textContent = 'Проверка рамки';
      document.getElementById('page-main').appendChild(panel);
      const results = [];
      for (const material of ['limestone','masonry','timber','obsidian','mossy','ember','golden','starlight']) {
        panel.dataset.mcMaterial = material;
        const widths = [];
        for (const [width,height] of [[280,240],[480,520],[900,240]]) {
          panel.style.width = width + 'px'; panel.style.height = height + 'px';
          const style = getComputedStyle(panel);
          widths.push(style.borderLeftWidth);
          const directory = {limestone:'flat-limestone',masonry:'flat-masonry',timber:'flat-timber',obsidian:'flat-obsidian',mossy:'mossy-flat',ember:'ember-flat',golden:'golden-flat',starlight:'starlight-flat'}[material];
          results.push(style.backgroundImage.includes('/'+directory+'/corner-tl') && style.backgroundRepeat.includes('repeat-x') && style.backgroundRepeat.includes('repeat-y'));
        }
        results.push(new Set(widths).size === 1);
      }
      panel.remove();
      return results.every(Boolean);
    });
    assert(variants, 'Frame corners or repeated edges depend on panel size');
    await page.setViewportSize({width:1440,height:1000});
    await login(config.sessions[1]);
    await page.goto(config.origin + '/settings/?tab=appearance');
    assert(await page.locator('html').getAttribute('data-appearance') === 'nexus','Account isolation failed');
    await choose('minecraft','dark');
    const identity = await page.locator('.mc-avatar').getAttribute('src');
    for (const theme of ['dark','light']) {
      await choose('minecraft',theme);
      assert(await page.locator('.mc-avatar').getAttribute('src') === identity,'Avatar changes with theme');
      for (const route of [config.pending,config.managedProfile]) {
        await page.goto(config.origin + route);
        await page.waitForLoadState('networkidle');
        const cards = page.locator('.card:has(> table)');
        assert(await cards.count() > 0,'Missing populated table fixture');
        for (const card of await cards.all()) {
          const intact = await card.evaluate(el => {
            const table=el.querySelector('table'),r=el.getBoundingClientRect(),t=table.getBoundingClientRect(),s=getComputedStyle(el);
            return t.left>=r.left+parseFloat(s.borderLeftWidth)-1 && t.right<=r.right-parseFloat(s.borderRightWidth)+1 && t.bottom<=r.bottom-parseFloat(s.borderBottomWidth)+1;
          });
          assert(intact,'Table overlaps its frame: '+route+' '+theme);
          const row=card.locator('tbody tr:visible').first();
          const before=await card.evaluate(el=>getComputedStyle(el).backgroundImage);
          await row.hover();
          const frameVisible=await card.evaluate(el=>{
            const r=el.getBoundingClientRect(),s=getComputedStyle(el),row=el.querySelector('tbody tr').getBoundingClientRect();
            const hit=document.elementFromPoint(r.left+parseFloat(s.borderLeftWidth)/2,row.y+row.height/2);
            return hit===el;
          });
          assert(frameVisible,'Hovered row covers frame: '+route+' '+theme);
          assert(await card.evaluate(el=>getComputedStyle(el).backgroundImage) === before,'Hover changes frame');
        }
        if(theme==='dark') assert(!await page.locator('.card').evaluateAll(els=>els.some(el=>getComputedStyle(el).backgroundImage.includes('/flat-timber/'))),'Daytime wood remains in dark profile');
        await page.evaluate(()=>window.scrollTo(0,0));
        checks++;
        await page.screenshot({path:path.join(output,(route===config.pending?'pending':'managed-profile')+'-'+theme+'.png'),fullPage:true,animations:'disabled'});
        for(const width of [768,390,320]) {
          await page.setViewportSize({width,height:1000});
          const fits=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1);
          if(!fits) {
            await page.screenshot({path:path.join(output,'overflow.png'),fullPage:true,animations:'disabled'});
            const outside=await page.evaluate(()=>[...document.querySelectorAll('#page-main *')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.right>innerWidth+1;}).slice(0,8).map(el=>({tag:el.tagName,class:el.className,width:el.getBoundingClientRect().width,right:el.getBoundingClientRect().right})));
            throw new Error('Manager table expands page: '+route+' '+theme+' '+width+' '+JSON.stringify(outside));
          }
          checks++;
          await page.screenshot({path:path.join(output,(route===config.pending?'pending':'managed-profile')+'-'+theme+'-'+width+'.png'),fullPage:true,animations:'disabled'});
        }
        await page.setViewportSize({width:1440,height:1000});
      }
    }
    await page.goto(config.origin+'/');
    const anchored=await page.evaluate(()=>{
      const a=document.querySelector('.sidebar').getBoundingClientRect(),b=document.querySelector('.mc-hanging-lantern').getBoundingClientRect();
      return b.left<a.right && b.right>a.right;
    });
    assert(anchored,'Lantern is detached from sidebar');
    assert(await page.locator('.sidebar .icon').evaluateAll(els=>els.every(el=>el.querySelector('svg'))),'Unconverted sidebar icon');
    await page.emulateMedia({reducedMotion:'reduce'});
    assert(await page.locator('.mc-ambient img').first().evaluate(el=>getComputedStyle(el).animationName)==='none','Reduced motion ignored');
    await page.emulateMedia({reducedMotion:'no-preference'});
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
