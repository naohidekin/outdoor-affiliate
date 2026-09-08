// This preference is not authentication and must never grant admin access.
export const ANALYTICS_EXCLUSION_COOKIE = "camp_analytics_excluded";
export const ANALYTICS_EXCLUSION_MAX_AGE = 60 * 60 * 24 * 365;
export const GA_MEASUREMENT_ID = "G-0F2R4RX636";

export function hasAnalyticsExclusion(cookie: string): boolean {
  return cookie.split(";").some(part => part.trim() === `${ANALYTICS_EXCLUSION_COOKIE}=1`);
}

export function isExcludedAnalyticsPath(path: string): boolean {
  return /^\/(admin|api|analytics-settings)(\/|$)/.test(path);
}

export function isAnalyticsExcluded(): boolean {
  if (typeof window === "undefined") return true;
  try {
    return isExcludedAnalyticsPath(window.location?.pathname ?? "")
      || (typeof document !== "undefined" && hasAnalyticsExclusion(document.cookie));
  } catch { return true; }
}

export function setAnalyticsExclusion(excluded: boolean): boolean {
  try {
    document.cookie = `${ANALYTICS_EXCLUSION_COOKIE}=${excluded ? "1" : ""}; Path=/; SameSite=Lax; Max-Age=${excluded ? ANALYTICS_EXCLUSION_MAX_AGE : 0}${window.location.protocol === "https:" ? "; Secure" : ""}`;
    window.dispatchEvent(new Event("camp-analytics-preference"));
    return hasAnalyticsExclusion(document.cookie) === excluded;
  } catch { return false; }
}

// Runs before GA can send automatic events, without making public pages dynamic.
export const analyticsGuardScript = `
(function(){
  function excluded(){return ['/admin','/api','/analytics-settings'].some(function(p){return location.pathname===p||location.pathname.indexOf(p+'/')===0;})||document.cookie.split(';').some(function(c){return c.trim()==='${ANALYTICS_EXCLUSION_COOKIE}=1';});}
  function sync(){window['ga-disable-${GA_MEASUREMENT_ID}']=excluded();}
  sync();
  window.addEventListener('camp-analytics-preference',sync);
  window.addEventListener('focus',sync);
  window.addEventListener('pageshow',sync);
})();`;
