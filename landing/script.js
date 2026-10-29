const toggle = document.querySelector('.menu-toggle');
const nav = document.querySelector('#nav-links');
function closeMenu() {
  toggle.setAttribute('aria-expanded', 'false');
  toggle.setAttribute('aria-label', '打开菜单');
  nav.classList.remove('open');
}
toggle.addEventListener('click', () => {
  const open = toggle.getAttribute('aria-expanded') !== 'true';
  toggle.setAttribute('aria-expanded', String(open));
  toggle.setAttribute('aria-label', open ? '关闭菜单' : '打开菜单');
  nav.classList.toggle('open', open);
});
nav.addEventListener('click', event => {
  if (event.target.closest('a')) closeMenu();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && nav.classList.contains('open')) {
    closeMenu();
    toggle.focus();
  }
});
if ('IntersectionObserver' in window && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.08 });
  document.documentElement.classList.add('js-motion');
  document.querySelectorAll('.reveal').forEach(element => observer.observe(element));
  const words = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('lit');
        words.unobserve(entry.target);
      }
    });
  }, { rootMargin: '0px 0px -20% 0px', threshold: 1 });
  document.querySelectorAll('.tag-word').forEach(line => {
    const text = line.textContent;
    line.classList.remove('tag-word');
    line.textContent = '';
    const parts = typeof Intl.Segmenter === 'function'
      ? [...new Intl.Segmenter('zh-CN', { granularity: 'word' }).segment(text)].map(part => part.segment)
      : [...text];
    parts.forEach((part, index) => {
      const span = document.createElement('span');
      span.textContent = part;
      span.className = 'tag-word';
      span.style.transitionDelay = `${index * 60}ms`;
      line.append(span);
      words.observe(span);
    });
  });
}
