/** Strict allowlist: never persist exception text, HTTP bodies, URLs, or secrets. */
const PHASES=new Set(['input_environment','dependency_setup','execution','product_updates','article_update','article_readback','cache_revalidation','public_readback','image_readback','subprocess']);
const OPS=new Set(['db_read_articles','db_read_products','db_patch_articles','db_patch_products']);
export function safeDiagnostic(value={}) {
 if(!value||typeof value!=='object')return {};
 const d={};
 if(PHASES.has(value.phase))d.phase=value.phase;
 if(OPS.has(value.operation))d.operation=value.operation;
 if(Number.isInteger(value.httpStatus)&&value.httpStatus>=100&&value.httpStatus<=599)d.httpStatus=value.httpStatus;
 if(typeof value.dbCode==='string'&&/^[A-Z0-9]{5}$/.test(value.dbCode))d.dbCode=value.dbCode;
 if(Number.isInteger(value.exitCode)&&value.exitCode>=-128&&value.exitCode<=255)d.exitCode=value.exitCode;
 if(value.timedOut===true)d.timedOut=true;
 return d;
}
