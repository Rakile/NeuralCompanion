import {policyContract,policySites} from './policyData';
export type Category=typeof policyContract.categories[number];
export type Level=typeof policyContract.levels[number];
export type Policy={version:1;revision:string;default_level:Level;categories:Partial<Record<Category,Level>>};
const levels:readonly string[]=policyContract.levels,categories:readonly string[]=policyContract.categories;
export function validatePolicy(raw:unknown):Policy{
  const p=raw as Policy;
  if(!p||typeof p!=='object'||Array.isArray(p)||Object.keys(p).sort().join(',')!=='categories,default_level,revision,version'
    ||p.version!==1||typeof p.revision!=='string'||!new RegExp(policyContract.revision_pattern).test(p.revision)
    ||!levels.includes(p.default_level)||!p.categories||typeof p.categories!=='object'||Array.isArray(p.categories)
    ||Object.entries(p.categories).some(([k,v])=>!categories.includes(k)||!levels.includes(v)))throw Error('diagnostic_policy_invalid');
  return {version:1,revision:p.revision,default_level:p.default_level,categories:{...p.categories}};
}
export class DiagnosticPolicy{
  private selected:Policy=validatePolicy(policyContract.default);
  applyPolicy(raw:unknown):string{
    const p=validatePolicy(raw);
    if(p.revision===this.selected.revision&&(p.default_level!==this.selected.default_level||
      categories.some(k=>p.categories[k as Category]!==this.selected.categories[k as Category])))throw Error('diagnostic_policy_revision_conflict');
    this.selected=p;return p.revision;
  }
  snapshot():Policy{return {...this.selected,categories:{...this.selected.categories}};}
  enabled(category:string,verbosity:string='trace',mandatory=false):boolean{
    if(mandatory)return true;
    const c=categories.includes(category)?category as Category:'uncategorized';
    const level=this.selected.categories[c]??this.selected.default_level;
    return level!=='off'&&levels.slice(1).includes(verbosity)&&levels.indexOf(level)>=levels.indexOf(verbosity);
  }
}
export function classify(site:string,level='debug',outcome='observed',data:Record<string,unknown>={}){
  const mandatory=level==='error'||level==='warning'||outcome==='failed'||outcome==='rejected'
    ||data.begin_recorded===true
    ||/(?:^|[._])(reject(?:ed|ion)?|fail(?:ed|ure)?|error|overflow|unavailable)(?:$|[._])/.test(site)
    ||policySites.mandatory_prefixes.some(p=>site.startsWith(p))||!!data.failure_kind
    ||data.state_after==='rejected'||data.state_after==='failed'
    ||(data.expected!=null&&Object.prototype.hasOwnProperty.call(data,'actual')&&data.expected!==data.actual
      &&!(policySites.nonfailure_conditions as readonly unknown[]).includes(data.condition));
  const match=policySites.prefixes.find(([p])=>site.startsWith(p));
  return {category:match?.[1]??'uncategorized',verbosity:match?.[2]??'trace',mandatory};
}
export const policy=new DiagnosticPolicy();
export function siteEnabled(site:string,level='debug',outcome='observed',data:Record<string,unknown>={}):boolean{
  const c=classify(site,level,outcome,data);return policy.enabled(c.category,c.verbosity,c.mandatory);
}
