/** Display-only cleanup; the original voice ID remains the assignment identity. */
export function readableVoiceName(label:string):string {
  return label.replace(/\.wav$/i,'').replace(/_[a-f0-9]{24,}$/i,'')
    .replace(/_/g,' ').replace(/\s+/g,' ').trim() || 'Unnamed voice';
}
