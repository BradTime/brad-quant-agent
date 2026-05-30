/**
 * 在 React 水合前剥离浏览器扩展注入的 DOM 属性，避免
 * 「server HTML 与 client properties 不一致」告警。
 *
 * 典型来源：密码管理器、Grammarly、购物/自动化类扩展（如 mpa-*）、翻译插件等。
 * 参考：https://github.com/vercel/next.js/discussions/72035
 */

export const HYDRATION_GUARD_SCRIPT = `(function(){var safe=new Set(["class","dir","lang","style","suppresshydrationwarning"]);var ext=/^(mpa-|data-new-gr-|data-gr-ext-|data-gr-|cz-shortcut|data-lt-|data-keeper|ff-meta|bis-|jss-|vsc-|__processed|spellcheck|autocomplete|lcm-|bis_register|data-1p-|data-arp)/i;function strip(el){if(!el||!el.getAttributeNames)return;Array.prototype.slice.call(el.getAttributeNames()).forEach(function(n){var l=n.toLowerCase();if(!safe.has(l)&&ext.test(l))el.removeAttribute(n);});}strip(document.documentElement);strip(document.body);try{var obs=new MutationObserver(function(rs){rs.forEach(function(r){if(r.type==="attributes"&&r.target)strip(r.target);});});obs.observe(document.documentElement,{attributes:true,subtree:false});obs.observe(document.body,{attributes:true,subtree:false});}catch(e){}})();`;
