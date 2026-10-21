(() => {
  const { ui, db } = App;
  const A = App.admin;
  const state = { q: '', cat: '', stock: '', status: '', sort: 'createdAt', dir: -1, selected: new Set() };

  function filtered() {
    let list = db.products.all();
    const q = state.q.toLowerCase().trim();
    if (q) list = list.filter((p) => db.products.searchText(p).includes(q) || p.specs.sku.toLowerCase().includes(q));
    if (state.cat) list = list.filter((p) => p.category === state.cat);
    if (state.stock === 'in') list = list.filter((p) => p.stock > 0);
    if (state.stock === 'low') list = list.filter((p) => p.stock > 0 && p.stock <= 5);
    if (state.stock === 'out') list = list.filter((p) => p.stock <= 0);
    if (state.status) list = list.filter((p) => (state.status === 'hidden') === (p.status === 'hidden'));
    const k = state.sort;
    return list.sort((a, b) => (typeof a[k] === 'number' ? a[k] - b[k] : String(a[k]).localeCompare(String(b[k]), 'ru')) * state.dir);
  }

  const select = (id, label, options, value) =>
    `<select class="select" id="${id}" aria-label="${label}">${options.map(([v, t]) => `<option value="${v}" ${value === v ? 'selected' : ''}>${t}</option>`).join('')}</select>`;

  function row(p) {
    const r = db.products.rating(p);
    const hidden = p.status === 'hidden';
    return `
      <tr class="${hidden ? 'is-hidden' : ''}">
        <td><input type="checkbox" class="row-check" data-sel="${p.id}" aria-label="Выбрать" ${state.selected.has(p.id) ? 'checked' : ''}></td>
        <td><a href="#product/${p.id}">${ui.img(p.images[0], '', 'adm-thumb')}</a></td>
        <td class="cell-name">
          <a href="#product/${p.id}"><b>${ui.esc(p.name)}</b></a>
          <small>${ui.esc(p.brand)}${p.specs.sku ? ' · ' + ui.esc(p.specs.sku) : ''}${r.count ? ` · ★ ${r.rating.toFixed(1)} (${r.count})` : ''}</small>
        </td>
        <td class="hide-sm">${ui.esc(A.catName(p.category))}<br><small class="muted">${ui.esc(A.subName(p.category, p.sub))}</small></td>
        <td><b>${ui.price(p.price)}</b>${p.oldPrice ? `<br><small class="muted price-was">${ui.price(p.oldPrice)}</small>` : ''}</td>
        <td><input class="stock-input ${p.stock <= 0 ? 'zero' : p.stock <= 5 ? 'low' : ''}" type="number" min="0" value="${p.stock}" data-stock="${p.id}" aria-label="Остаток"></td>
        <td class="hide-sm"><div class="flags">
          ${hidden ? '<span class="tag tag-muted">Скрыт</span>' : ''}${p.isHit ? '<span class="tag">Хит</span>' : ''}${p.isNew ? '<span class="tag">Новинка</span>' : ''}
          ${p.isPopular ? '<span class="tag tag-soft">Популярное</span>' : ''}${p.oldPrice ? '<span class="tag tag-sale">Скидка</span>' : ''}
        </div></td>
        <td><div class="row-actions">
          <button type="button" data-toggle-status="${p.id}" title="${hidden ? 'Показать на сайте' : 'Скрыть с сайта'}" aria-label="${hidden ? 'Показать на сайте' : 'Скрыть с сайта'}">${ui.icon(hidden ? 'eye-off' : 'eye')}</button>
          <a href="${ui.productUrl(p)}" target="_blank" rel="noopener" title="Открыть на сайте" aria-label="Открыть на сайте">${ui.icon('external')}</a>
          <a href="#product/${p.id}" title="Редактировать" aria-label="Редактировать">${ui.icon('edit')}</a>
          <button type="button" data-dup="${p.id}" title="Сделать копию" aria-label="Сделать копию">${ui.icon('copy')}</button>
          <button type="button" class="del" data-del="${p.id}" title="Удалить" aria-label="Удалить">${ui.icon('trash')}</button>
        </div></td>
      </tr>`;
  }

  function products() {
    A.setTitle('Товары');
    A.$content.innerHTML = `
      <div class="adm-toolbar">
        <div class="search">${ui.icon('search')}<input class="input" type="search" id="p-q" placeholder="Название, бренд, тег или артикул" value="${ui.esc(state.q)}"></div>
        ${select('p-cat', 'Категория', [['', 'Все категории']].concat(db.categories.all().map((c) => [c.id, c.name])), state.cat)}
        ${select(
          'p-stock',
          'Наличие',
          [
            ['', 'Любое наличие'],
            ['in', 'В наличии'],
            ['low', 'Мало (≤ 5)'],
            ['out', 'Нет в наличии']
          ],
          state.stock
        )}
        ${select(
          'p-status',
          'Публикация',
          [
            ['', 'Все товары'],
            ['published', 'На сайте'],
            ['hidden', 'Скрытые']
          ],
          state.status
        )}
        <div class="right"><a class="btn btn-primary btn-sm" href="#product/new">${ui.icon('plus')} Добавить товар</a></div>
      </div>
      <div class="bulk-bar" id="bulk"><span id="bulk-n"></span>
        <button type="button" data-bulk="hide">Скрыть</button><button type="button" data-bulk="show">Показать</button>
        <button type="button" data-bulk="delete">Удалить</button><button type="button" data-bulk="clear">Снять выделение</button>
      </div>
      <section class="adm-card"><div class="adm-table-wrap" id="p-table"></div></section>`;

    let visible = [];
    const th = (key, label, cls) =>
      `<th class="${cls || ''}"><button type="button" data-sort="${key}">${label}${state.sort === key ? ui.icon(state.dir > 0 ? 'chevron-up' : 'chevron-down') : ''}</button></th>`;
    const draw = () => {
      visible = filtered();
      document.getElementById('p-table').innerHTML = visible.length
        ? `<table class="adm-table adm-table-cards">
            <thead><tr>
              <th class="col-check"><input type="checkbox" class="row-check" id="sel-all" aria-label="Выбрать все" ${visible.every((p) => state.selected.has(p.id)) ? 'checked' : ''}></th>
              <th></th>${th('name', 'Товар')}${th('category', 'Категория', 'hide-sm')}${th('price', 'Цена')}${th('stock', 'Остаток')}<th class="hide-sm">Метки</th><th></th>
            </tr></thead>
            <tbody>${visible.map(row).join('')}</tbody>
          </table>`
        : '<div class="adm-empty">Товары не найдены. <a href="#product/new">Добавить товар</a></div>';
      const n = state.selected.size;
      document.getElementById('bulk').classList.toggle('is-visible', n > 0);
      document.getElementById('bulk-n').textContent = `Выбрано: ${n}`;
    };
    draw();

    document.getElementById('p-q').addEventListener(
      'input',
      ui.debounce((e) => ((state.q = e.target.value), draw()), 200)
    );
    ['cat', 'stock', 'status'].forEach((k) => (document.getElementById('p-' + k).onchange = (e) => ((state[k] = e.target.value), draw())));

    A.$content.onclick = async (e) => {
      const t = (sel) => e.target.closest(sel);
      if (t('[data-sort]')) {
        const key = t('[data-sort]').dataset.sort;
        state.dir = state.sort === key ? -state.dir : 1;
        state.sort = key;
        return draw();
      }
      if (t('[data-toggle-status]')) {
        const p = db.products.get(t('[data-toggle-status]').dataset.toggleStatus);
        const hide = p.status !== 'hidden';
        await db.products.save({ id: p.id, status: hide ? 'hidden' : 'published' });
        ui.toast({ title: hide ? 'Товар скрыт с сайта' : 'Товар снова на сайте', text: p.name, icon: hide ? 'eye-off' : 'eye' });
        return draw();
      }
      if (t('[data-del]')) {
        const p = db.products.get(t('[data-del]').dataset.del);
        if (!(await ui.confirm(`Удалить «${p.name}»? Действие нельзя отменить.`))) return;
        await db.products.remove(p.id);
        state.selected.delete(p.id);
        ui.toast({ title: 'Товар удалён', icon: 'trash' });
        return draw();
      }
      if (t('[data-dup]')) {
        const copy = db.products.normalize(db.products.get(t('[data-dup]').dataset.dup));
        delete copy.id;
        copy.name += ' (копия)';
        copy.slug = A.uniqueSlug(db.products.slugify(copy.name));
        copy.status = 'hidden';
        const saved = await db.products.save(copy);
        if (saved) {
          ui.toast({ title: 'Копия создана', text: 'Она скрыта с сайта — проверьте и опубликуйте' });
          location.hash = 'product/' + saved.id;
        }
        return;
      }
      const bulk = t('[data-bulk]');
      if (!bulk) return;
      const ids = [...state.selected];
      const action = bulk.dataset.bulk;
      if (action === 'clear') state.selected.clear();
      if (action === 'hide' || action === 'show') {
        for (const id of ids) await db.products.save({ id, status: action === 'hide' ? 'hidden' : 'published' });
        ui.toast({ title: action === 'hide' ? `Скрыто товаров: ${ids.length}` : `Показано товаров: ${ids.length}` });
      }
      if (action === 'delete') {
        if (!(await ui.confirm(`Удалить выбранные товары (${ids.length})? Действие нельзя отменить.`))) return;
        for (const id of ids) await db.products.remove(id);
        state.selected.clear();
        ui.toast({ title: `Удалено товаров: ${ids.length}`, icon: 'trash' });
      }
      draw();
    };

    A.$content.onchange = async (e) => {
      const el = e.target;
      if (el.id === 'sel-all') visible.forEach((p) => (el.checked ? state.selected.add(p.id) : state.selected.delete(p.id)));
      else if (el.dataset.sel) el.checked ? state.selected.add(el.dataset.sel) : state.selected.delete(el.dataset.sel);
      else if (el.dataset.stock) {
        const value = Math.max(0, parseInt(el.value, 10) || 0);
        await db.products.save({ id: el.dataset.stock, stock: value });
        ui.toast({ title: 'Остаток обновлён', text: value + ' шт.' });
      } else return;
      draw();
    };
  }

  A.uniqueSlug = (base, exceptId) => {
    const all = db.products.all();
    let slug = base;
    let i = 2;
    while (all.some((p) => p.slug === slug && p.id !== exceptId)) slug = base + '-' + i++;
    return slug;
  };

  A.views.products = products;
})();
