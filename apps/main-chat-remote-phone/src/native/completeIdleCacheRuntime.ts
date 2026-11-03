import type {OrderedIdleInventory,OrderedIdleInventoryStatus} from '../dev/orderedIdleInventory';
let selected:Readonly<{owner:object;inventory:OrderedIdleInventory}>|null=null;
let status:OrderedIdleInventoryStatus|null=null;
export function attachCompleteIdleInventory(owner:object,inventory:OrderedIdleInventory){selected={owner,inventory};status=inventory.status;}
export function publishCompleteIdleStatus(owner:object,value:OrderedIdleInventoryStatus){if(selected?.owner===owner)status=value;}
export function detachCompleteIdleInventory(owner:object){if(selected?.owner===owner){selected=null;status=null;}}
export const completeIdleCacheStatus=()=>status;
export async function clearCompleteIdleCache():Promise<boolean>{
  const current=selected;if(!current)return false;
  await current.inventory.clear();return true;
}
