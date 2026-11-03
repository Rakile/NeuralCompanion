export function reorderReply(queue: readonly {id:string}[], id: string, destination: number): string[] {
  const ids = queue.map(item=>item.id), source = ids.indexOf(id);
  if (source < 0 || !Number.isInteger(destination)) throw new Error('Queue item changed.');
  ids.splice(source,1); ids.splice(Math.max(0,Math.min(ids.length,destination)),0,id);
  return ids;
}
