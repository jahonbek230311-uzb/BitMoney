/* Theme preference is managed on its own page. System mode follows the device. */
(function () {
  var root = document.documentElement;
  function resolvedTheme(choice) {
    return choice === 'system' ? (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : choice;
  }
  function applyTheme(choice, animate) {
    var actual = resolvedTheme(choice);
    if (animate) {
      document.body.classList.add('theme-wipe');
      window.setTimeout(function () { root.dataset.theme = actual; }, 170);
      window.setTimeout(function () { document.body.classList.remove('theme-wipe'); }, 580);
    } else root.dataset.theme = actual;
    try { localStorage.setItem('theme', choice); } catch (e) {}
    document.querySelectorAll('[data-set-theme]').forEach(function (button) {
      var active = button.dataset.setTheme === choice;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    var themeMeta = document.getElementById('theme-color-meta');
    if (themeMeta) themeMeta.setAttribute('content', actual === 'dark' ? '#080c14' : '#ffffff');
    if (window.monaco && window.monaco.editor) window.monaco.editor.setTheme(actual === 'dark' ? 'vs-dark' : 'vs');
  }
  var saved = 'dark';
  try { saved = localStorage.getItem('theme') || 'dark'; } catch (e) {}
  applyTheme(saved, false);
  document.querySelectorAll('[data-set-theme]').forEach(function (button) {
    button.addEventListener('click', function () { applyTheme(button.dataset.setTheme, true); });
  });
  if (window.matchMedia) {
    var media = window.matchMedia('(prefers-color-scheme: light)');
    var updateSystem = function () { var choice = 'dark'; try { choice = localStorage.getItem('theme') || 'dark'; } catch (e) {} if (choice === 'system') applyTheme('system', false); };
    if (media.addEventListener) media.addEventListener('change', updateSystem); else if (media.addListener) media.addListener(updateSystem);
  }
})();
(function () {
  var burger = document.getElementById('burger');
  var nav = document.getElementById('nav');
  var backdrop = document.getElementById('nav-backdrop');
  var closeButton = document.getElementById('nav-close');
  if (!burger || !nav || !backdrop) return;
  function closeMenu() {
    nav.classList.remove('open');
    backdrop.hidden = true;
    document.body.classList.remove('nav-open');
    burger.setAttribute('aria-expanded', 'false');
    burger.setAttribute('aria-label', 'Open navigation menu');
  }
  function openMenu() {
    nav.classList.add('open');
    backdrop.hidden = false;
    document.body.classList.add('nav-open');
    burger.setAttribute('aria-expanded', 'true');
    burger.setAttribute('aria-label', 'Close navigation menu');
  }
  burger.addEventListener('click', function () {
    nav.classList.contains('open') ? closeMenu() : openMenu();
  });
  backdrop.addEventListener('click', closeMenu);
  if (closeButton) closeButton.addEventListener('click', closeMenu);
  nav.querySelectorAll('a').forEach(function (a) { a.addEventListener('click', closeMenu); });
  nav.querySelectorAll('form').forEach(function (f) { f.addEventListener('submit', closeMenu); });
  // Close on outside taps and a deliberate left-swipe gesture on the drawer.
  var touchX = 0, touchY = 0;
  nav.addEventListener('touchstart', function (e) {
    if (!e.touches || !e.touches.length) return;
    touchX = e.touches[0].clientX; touchY = e.touches[0].clientY;
  }, {passive:true});
  nav.addEventListener('touchend', function (e) {
    if (!e.changedTouches || !e.changedTouches.length) return;
    var dx = e.changedTouches[0].clientX - touchX;
    var dy = e.changedTouches[0].clientY - touchY;
    if (dx < -70 && Math.abs(dx) > Math.abs(dy) * 1.2) closeMenu();
  }, {passive:true});
  // Any tap/click outside the drawer (including the visible right side) closes it.
  document.addEventListener('pointerdown', function (e) {
    if (!nav.classList.contains('open')) return;
    if (nav.contains(e.target) || burger.contains(e.target)) return;
    closeMenu();
  }, true);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeMenu(); });
  window.addEventListener('resize', function () { if (window.innerWidth > 800) closeMenu(); });
})();

/* ---- times, forms and countdowns (display only; the SERVER enforces every deadline) ---- */
(function () {
  function pad(n) { return String(n).padStart(2, '0'); }
  function localInput(d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  document.querySelectorAll('[data-utc]').forEach(function (el) {
    var d = new Date(el.dataset.utc); if (isNaN(d)) return;
    if (el.tagName === 'INPUT') el.value = localInput(d); else el.textContent = d.toLocaleString();
  });
  document.querySelectorAll('form.tz-form').forEach(function (f) {
    f.addEventListener('submit', function () {
      f.querySelectorAll('input[data-iso-target]').forEach(function (i) {
        var t = f.querySelector('[name="' + i.dataset.isoTarget + '"]');
        t.value = i.value ? new Date(i.value).toISOString() : '';
      });
    });
  });
  document.querySelectorAll('[data-countdown]').forEach(function (el) {
    var target = new Date(el.dataset.countdown).getTime();
    var offset = new Date(el.dataset.now).getTime() - Date.now();   // server clock minus local clock
    (function tick() {
      var s = Math.floor((target - (Date.now() + offset)) / 1000);
      if (s <= 0) {
        el.textContent = '00:00:00';
        var last = 0; try { last = +sessionStorage.getItem('cdReload') || 0; } catch (e) {}
        if (Date.now() - last > 10000) { try { sessionStorage.setItem('cdReload', Date.now()); } catch (e) {} setTimeout(function () { location.reload(); }, 1200); }
        return;
      }
      var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
      el.textContent = (d ? d + 'd ' : '') + pad(h) + ':' + pad(m) + ':' + pad(s % 60);
      setTimeout(tick, 500);
    })();
  });
  var dl = document.getElementById('dl-created');
  if (dl) dl.addEventListener('click', function () {
    var lines = ['username,password'];
    document.querySelectorAll('#created tr').forEach(function (tr, i) { if (i) lines.push(tr.cells[0].textContent + ',' + tr.cells[1].textContent); });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([lines.join('\r\n')], { type: 'text/csv' }));
    a.download = 'accounts.csv'; document.body.appendChild(a); a.click(); a.remove();
  });
})();

/* ---- admin contest: filter the user list, select the visible ones ---- */
(function () {
  var f = document.getElementById('pfilter'), list = document.getElementById('ulist');
  if (!f || !list) return;
  var labels = list.querySelectorAll('label'), count = document.getElementById('pcount');
  function apply() {
    var q = f.value.trim().toLowerCase(), n = 0;
    labels.forEach(function (l) { var show = !q || l.textContent.toLowerCase().indexOf(q) !== -1; l.style.display = show ? '' : 'none'; if (show) n++; });
    if (count) count.textContent = n + ' shown';
  }
  f.addEventListener('input', apply); apply();
  f.addEventListener('keydown', function (e) { if (e.key === 'Enter') e.preventDefault(); });
  function setShown(v) { labels.forEach(function (l) { if (l.style.display !== 'none') l.querySelector('input').checked = v; }); }
  document.getElementById('psel').addEventListener('click', function () { setShown(true); });
  document.getElementById('pclr').addEventListener('click', function () { setShown(false); });
})();

/* Whole-interface localization. Text nodes are translated from their original English text,
   so changing languages repeatedly never corrupts or compounds a previous translation. */
(function(){
  var select=document.getElementById('ui-language');
  var dictionaries={
    en:{},
    uz:{
      'Home':'Bosh sahifa','Problems':'Masalalar','Contests':'Musobaqalar','Standings':'Reyting jadvali','My submissions':'Yuborgan yechimlarim','Profile':'Profil','Admin':'Admin panel','Theme':'Mavzu','Login':'Kirish','Register':'Ro‘yxatdan o‘tish','Language':'Til','Close menu':'Menyuni yopish','Logout':'Chiqish','Code. Compete. Win.':'Kod yoz. Bellash. G‘alaba qozon.','Browse contests':'Musobaqalarni ko‘rish','Explore problems':'Masalalarni ko‘rish','Explore contests':'Musobaqalarni ko‘rish','Published problems':'Ochiq masalalar','Practice problems':'Mashq masalalari','Live contests':'Jonli musobaqalar','Trusted judging':'Ishonchli tekshiruv','Classroom ready':'Sinf uchun tayyor','Choose a theme. Your preference is saved on this device and applied across Bit Money.':'Mavzuni tanlang. Tanlovingiz ushbu qurilmada saqlanadi va Bit Money bo‘ylab qo‘llanadi.','Personalize your workspace':'Ish muhitingizni sozlang','Instant preview':'Darhol ko‘rish','Bright surfaces and crisp contrast.':'Yorqin fon va aniq kontrast.','Deep navy, neon green, and cyan.':'To‘q ko‘k, neon yashil va havorang.','Follow your device appearance.':'Qurilmangiz ko‘rinishiga moslashish.','Create contest':'Musobaqa yaratish','Create a new problem for this contest':'Ushbu musobaqa uchun yangi masala yaratish','Description':'Tavsif','Constraints':'Cheklovlar','Input':'Kirish ma’lumotlari','Expected output':'Kutilgan natija','Input format':'Kirish formati','Output format':'Chiqish formati','Duration (minutes)':'Davomiyligi (daqiqa)','Create':'Yaratish','Save':'Saqlash','Cancel':'Bekor qilish','Delete':'O‘chirish','Edit':'Tahrirlash','Preview':'Ko‘rib chiqish','Publish':'E’lon qilish','Duplicate':'Nusxalash','Status':'Holat','Actions':'Amallar','Action':'Amal','Category':'Turkum','Difficulty':'Qiyinlik','Filter':'Filtrlash','Search':'Qidirish','Submit':'Yuborish','Submissions':'Yechimlar','Accepted':'Qabul qilindi','Pending':'Kutilmoqda','Users':'Foydalanuvchilar','Problems':'Masalalar','Published':'E’lon qilingan','Dashboard':'Boshqaruv paneli','Admin workspace':'Admin ish maydoni','Choose an area to manage. Each tool opens its dedicated workspace.':'Boshqarish bo‘limini tanlang. Har bir vosita alohida sahifada ochiladi.','Create accounts and manage permissions.':'Hisoblar yarating va ruxsatlarni boshqaring.','Download CSV':'CSV yuklab olish','Export CSV':'CSV eksport qilish','Clear shown':'Ko‘rsatilganlarni tozalash','How many (max 200)':'Soni (eng ko‘pi 200)','Test maydonlarini yaratish':'Test maydonlarini yaratish','Reference solution':'Etalon yechim','Manual testlar':'Qo‘lda kiritilgan testlar','Input size':'Kirish hajmi','First number':'Birinchi son','Example':'Misol','Back to contest':'Musobaqaga qaytish','Add':'Qo‘shish','Add problem':'Masala qo‘shish','Go to problems':'Masalalarga o‘tish','Get started':'Boshlash','Enter platform':'Platformaga kirish','Start coding':'Dasturlashni boshlash','Ready to submit':'Yuborishga tayyor','Fast judging':'Tezkor tekshiruv','Overall standings':'Umumiy reyting','No students yet.':'Hozircha o‘quvchilar yo‘q.'
    },
    ru:{
      'Home':'Главная','Problems':'Задачи','Contests':'Контесты','Standings':'Таблица рейтинга','My submissions':'Мои отправки','Profile':'Профиль','Admin':'Панель администратора','Theme':'Тема','Login':'Войти','Register':'Регистрация','Language':'Язык','Close menu':'Закрыть меню','Logout':'Выйти','Code. Compete. Win.':'Пиши код. Соревнуйся. Побеждай.','Browse contests':'Смотреть контесты','Explore problems':'Смотреть задачи','Explore contests':'Смотреть контесты','Published problems':'Опубликованные задачи','Practice problems':'Задачи для практики','Live contests':'Текущие контесты','Trusted judging':'Надёжная проверка','Classroom ready':'Для учебного класса','Choose a theme. Your preference is saved on this device and applied across Bit Money.':'Выберите тему. Выбор сохранится на этом устройстве и будет применяться во всём Bit Money.','Personalize your workspace':'Настройте рабочее пространство','Instant preview':'Мгновенный просмотр','Bright surfaces and crisp contrast.':'Светлый интерфейс и чёткий контраст.','Deep navy, neon green, and cyan.':'Тёмно-синий, неоново-зелёный и голубой.','Follow your device appearance.':'Следовать настройкам устройства.','Create contest':'Создать контест','Create a new problem for this contest':'Создать задачу для этого контеста','Description':'Описание','Constraints':'Ограничения','Input':'Входные данные','Expected output':'Ожидаемый результат','Input format':'Формат входных данных','Output format':'Формат выходных данных','Duration (minutes)':'Длительность (минуты)','Create':'Создать','Save':'Сохранить','Cancel':'Отмена','Delete':'Удалить','Edit':'Изменить','Preview':'Предпросмотр','Publish':'Опубликовать','Duplicate':'Дублировать','Status':'Статус','Actions':'Действия','Action':'Действие','Category':'Категория','Difficulty':'Сложность','Filter':'Фильтр','Search':'Поиск','Submit':'Отправить','Submissions':'Отправки','Accepted':'Принято','Pending':'Ожидает','Users':'Пользователи','Published':'Опубликовано','Dashboard':'Панель управления','Admin workspace':'Рабочая область администратора','Choose an area to manage. Each tool opens its dedicated workspace.':'Выберите раздел управления. Каждый инструмент открывается на отдельной странице.','Create accounts and manage permissions.':'Создавайте аккаунты и управляйте правами.','Download CSV':'Скачать CSV','Export CSV':'Экспорт CSV','Clear shown':'Очистить показанные','How many (max 200)':'Количество (максимум 200)','Reference solution':'Эталонное решение','Manual testlar':'Ручные тесты','Input size':'Размер входных данных','First number':'Первое число','Example':'Пример','Back to contest':'Назад к контесту','Add':'Добавить','Add problem':'Добавить задачу','Go to problems':'Перейти к задачам','Get started':'Начать','Enter platform':'Войти на платформу','Start coding':'Начать программировать','Ready to submit':'Готово к отправке','Fast judging':'Быстрая проверка','Overall standings':'Общий рейтинг','No students yet.':'Пока нет учеников.'
    },
    tg:{
      'Home':'Асосӣ','Problems':'Масъалаҳо','Contests':'Озмунҳо','Standings':'Ҷадвали рейтинг','My submissions':'Ҳалли фиристодаи ман','Profile':'Профил','Admin':'Панели админ','Theme':'Мавзуъ','Login':'Вуруд','Register':'Сабти ном','Language':'Забон','Close menu':'Пӯшидани меню','Logout':'Баромадан','Code. Compete. Win.':'Рамз навис. Рақобат кун. Ғолиб шав.','Browse contests':'Дидани озмунҳо','Explore problems':'Дидани масъалаҳо','Explore contests':'Дидани озмунҳо','Published problems':'Масъалаҳои нашршуда','Practice problems':'Масъалаҳои машқӣ','Live contests':'Озмунҳои ҷорӣ','Trusted judging':'Санҷиши боэътимод','Classroom ready':'Барои синф омода','Choose a theme. Your preference is saved on this device and applied across Bit Money.':'Мавзӯъро интихоб кунед. Ин интихоб дар дастгоҳ нигоҳ дошта шуда, дар тамоми Bit Money истифода мешавад.','Personalize your workspace':'Муҳити кори худро танзим кунед','Instant preview':'Пешнамоиши фаврӣ','Bright surfaces and crisp contrast.':'Заминаи равшан ва контрасти возеҳ.','Deep navy, neon green, and cyan.':'Кабуди тира, сабзи неонӣ ва кабуди равшан.','Follow your device appearance.':'Ба намуди дастгоҳ пайравӣ кардан.','Create contest':'Эҷоди озмун','Create a new problem for this contest':'Барои ин озмун масъалаи нав эҷод кунед','Description':'Тавсиф','Constraints':'Маҳдудиятҳо','Input':'Вуруд','Expected output':'Натиҷаи интизорӣ','Input format':'Формати вуруд','Output format':'Формати баромад','Duration (minutes)':'Давомнокӣ (дақиқа)','Create':'Эҷод кардан','Save':'Захира кардан','Cancel':'Бекор кардан','Delete':'Нест кардан','Edit':'Таҳрир кардан','Preview':'Пешнамоиш','Publish':'Нашр кардан','Duplicate':'Нусха бардоштан','Status':'Ҳолат','Actions':'Амалҳо','Action':'Амал','Category':'Категория','Difficulty':'Душворӣ','Filter':'Филтр','Search':'Ҷустуҷӯ','Submit':'Фиристодан','Submissions':'Ҳалҳои фиристода','Accepted':'Қабул шуд','Pending':'Дар интизорӣ','Users':'Истифодабарандагон','Published':'Нашршуда','Dashboard':'Панели идоракунӣ','Admin workspace':'Муҳити кори администратор','Choose an area to manage. Each tool opens its dedicated workspace.':'Қисми идоракуниро интихоб кунед. Ҳар восита дар саҳифаи алоҳида кушода мешавад.','Create accounts and manage permissions.':'Ҳисобҳо созед ва иҷозатҳоро идора кунед.','Download CSV':'Боргирии CSV','Export CSV':'Содироти CSV','Clear shown':'Тоза кардани нишоншудаҳо','How many (max 200)':'Шумора (ҳадди аксар 200)','Reference solution':'Ҳалли намунавӣ','Manual testlar':'Тестҳои дастӣ','Input size':'Андозаи вуруд','First number':'Рақами аввал','Example':'Намуна','Back to contest':'Бозгашт ба озмун','Add':'Илова кардан','Add problem':'Иловаи масъала','Go to problems':'Ба масъалаҳо гузаштан','Get started':'Оғоз кардан','Enter platform':'Ба платформа даромадан','Start coding':'Барномасозиро оғоз кунед','Ready to submit':'Барои фиристодан омода','Fast judging':'Санҷиши зуд','Overall standings':'Рейтинги умумӣ','No students yet.':'Ҳоло хонанда нест.'
    }
  };
  var originalNodes=new WeakMap();
  function apply(lang){
    lang=dictionaries[lang]?lang:'en';
    document.documentElement.lang=lang==='tg'?'tg':lang;
    try{localStorage.setItem('ui-language',lang)}catch(e){}
    if(select)select.value=lang;
    var dict=dictionaries[lang];
    var walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT,{acceptNode:function(n){
      if(!n.parentElement||/^(SCRIPT|STYLE|TEXTAREA|CODE|PRE|OPTION)$/.test(n.parentElement.tagName))return NodeFilter.FILTER_REJECT;
      if(n.parentElement.closest('input,textarea,script,style,code,pre,[data-no-translate]'))return NodeFilter.FILTER_REJECT;
      return n.nodeValue.trim()?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT;
    }});
    var nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
    nodes.forEach(function(node){
      if(!originalNodes.has(node))originalNodes.set(node,node.nodeValue);
      var original=originalNodes.get(node), trimmed=original.trim();
      if(!dict[trimmed]){
        var keys=Object.keys(dict).sort(function(a,b){return b.length-a.length;});
        var translated=trimmed;
        keys.forEach(function(key){translated=translated.split(key).join(dict[key]);});
        if(translated===trimmed)return;
        node.nodeValue=original.replace(trimmed,translated);
      }else node.nodeValue=original.replace(trimmed,dict[trimmed]);
    });
    var nav=document.getElementById('nav');
    if(nav){var close=nav.querySelector('.nav-close span');if(close)close.textContent=dict['Close menu']||'Close menu';var label=nav.querySelector('.language-picker > span');if(label)label.textContent=dict.Language||'Language';}
  }
  var initial='en';try{initial=localStorage.getItem('ui-language')||'en'}catch(e){}
  apply(initial);if(select)select.addEventListener('change',function(){apply(select.value)});
})();
