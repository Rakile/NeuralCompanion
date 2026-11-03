import * as SecureStore from 'expo-secure-store';
import * as Crypto from 'expo-crypto';
import {OrderedRecoveryJournal} from '../dev/desktopOrderedRecovery';

export const orderedRecoveryJournal=new OrderedRecoveryJournal({
  read:scope=>SecureStore.getItemAsync('nc-ordered-recovery-v1-'+scope),
  write:(scope,value)=>SecureStore.setItemAsync('nc-ordered-recovery-v1-'+scope,value,
    {keychainAccessible:SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY}),
  random:async count=>Array.from(await Crypto.getRandomBytesAsync(count),b=>b.toString(16).padStart(2,'0')).join(''),
});
/** Input contains saved profile credentials, not an ephemeral peer identity.
 * Only its digest is used as a local key; neither value enters diagnostics. */
export const orderedRecoveryScope=(profile:string)=>Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256,profile);
