import {recordPhoneDebug} from './phoneDebugBridge';
import {orderedFailureDetails} from '../dev/desktopOrderedProtocol';

/** Error-only evidence; no owner credentials, paths or arbitrary native text. */
export function reportOrderedIdleFailure(stage:'manifest'|'acquisition',error:unknown):void {
  try {void recordPhoneDebug('warning','ordered_idle_inventory_failed',{
    stage,...orderedFailureDetails(error),
  }).catch(()=>undefined);}catch{} // Logging never joins the download or playback worker.
}

/** One-per-reason coalescing is owned by the cache coordinator. A recovered
 * decoder/inventory failure still needs evidence when optional logging is OFF. */
export function reportOrderedIdleRecovery(reason:string):void {
  if(reason!=='ordered_cached_inventory'&&reason!=='ordered_cached_inventory_pending'
    &&!/^ordered\.cached_renderer_(decode|presentation_timeout|renderer)$/.test(reason))return;
  try{void recordPhoneDebug('warning','ordered_cached_idle_recovered',{reason}).catch(()=>undefined);}catch{}
}
