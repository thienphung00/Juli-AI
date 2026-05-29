import { WORKSPACE_MODE_STORAGE_KEY } from "./workspace-mode";

/** Inline script applied in <head> before React hydrates to avoid theme flash. */
export const WORKSPACE_THEME_INIT_SCRIPT = `(function(){try{var m=localStorage.getItem("${WORKSPACE_MODE_STORAGE_KEY}");var r=document.documentElement;if(m==="affiliate"){r.classList.remove("dark");}else if(m==="seller"){r.classList.add("dark");}}catch(e){}})();`;
