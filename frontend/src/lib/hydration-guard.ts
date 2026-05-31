/**
 * 在 React 水合前剥离浏览器扩展注入的 DOM 属性，避免
 * 「server HTML 与 client properties 不一致」告警。
 *
 * 典型来源：密码管理器、Grammarly、购物/自动化类扩展（如 mpa-*）、翻译插件等。
 * 参考：https://github.com/vercel/next.js/discussions/72035
 */

export const HYDRATION_GUARD_SCRIPT = `(function(){var safe=new Set(["class","dir","lang","style","suppresshydrationwarning"]);var ext=/^(mpa-|data-new-gr-|data-gr-ext-|data-gr-|cz-shortcut|data-lt-|data-keeper|ff-meta|bis-|jss-|vsc-|__processed|spellcheck|autocomplete|lcm-|bis_register|data-1p-|data-arp)/i;function strip(el){if(!el||!el.getAttributeNames)return;Array.prototype.slice.call(el.getAttributeNames()).forEach(function(n){var l=n.toLowerCase();if(!safe.has(l)&&ext.test(l))el.removeAttribute(n);});}strip(document.documentElement);strip(document.body);try{var obs=new MutationObserver(function(rs){rs.forEach(function(r){if(r.type==="attributes"&&r.target)strip(r.target);});});obs.observe(document.documentElement,{attributes:true,subtree:false});obs.observe(document.body,{attributes:true,subtree:false});}catch(e){}})();`;

/**
 * 在首帧绘制前按持久化偏好设好明暗主题 class，消除刷新时的"先白后暗"闪烁(FOUC)。
 * 读取 zustand persist 的 `theme-storage`（形如 {"state":{"theme":"dark"}}），
 * system 时按系统配色解析。与 ThemeProvider 的 useEffect 幂等。
 */
export const THEME_INIT_SCRIPT = `(function(){try{var t="system";var raw=localStorage.getItem("theme-storage");if(raw){var s=(JSON.parse(raw)||{}).state;if(s&&s.theme)t=s.theme;}var d=t==="dark"||(t==="system"&&window.matchMedia&&window.matchMedia("(prefers-color-scheme: dark)").matches);var r=document.documentElement;r.classList.remove("light","dark");r.classList.add(d?"dark":"light");}catch(e){}})();`;
