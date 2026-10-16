/* 三页导航：页面切换只读缓存，不触发外部采集。 */
(()=>{
 const names=['market','research','account'];let active='market';
 function go(name){
  if(!names.includes(name))name='market';active=name;
  for(const page of names){$(page+'-page').hidden=page!==name;document.querySelector(`[data-page="${page}"]`).setAttribute('aria-selected',String(page===name))}
  document.querySelector('main').classList.toggle('market-layout',name==='market');
  if(location.hash!=='#'+name)history.replaceState(null,'','#'+name);
  requestAnimationFrame(()=>charts.forEach(c=>{const n=c.getDom();if(n.clientWidth&&n.clientHeight)c.resize()}));
  document.dispatchEvent(new CustomEvent('dashboard:page',{detail:name}));
 }
 $('page-tabs').addEventListener('click',e=>{const b=e.target.closest('[data-page]');if(b)go(b.dataset.page)});
 window.addEventListener('hashchange',()=>go(location.hash.slice(1)));
 window.DashboardNavigation={go,get active(){return active}};
 const init=()=>go(location.hash.slice(1));
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
