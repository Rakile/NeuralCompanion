using System.IO;

namespace NC.VSeeFaceBridge
{
    public static class StateFile
    {
        public static StreamReader OpenReader(string path)
        {
            // NC replaces whole snapshots atomically. Windows readers must permit
            // deletion/rename, otherwise a live read blocks os.replace in NC.
            return new StreamReader(new FileStream(path, FileMode.Open, FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete));
        }

        public static string TryRead(string path)
        {
            try
            {
                using (StreamReader reader = OpenReader(path)) return reader.ReadToEnd();
            }
            catch (FileNotFoundException) { return null; }
            catch (IOException error)
            {
                // A snapshot can be replaced between lookup and opening the handle.
                // Retry on the next Unity frame; the existing clock watchdog still applies.
                if ((error.HResult & 0xffff) == 32 || (error.HResult & 0xffff) == 33) return null;
                throw;
            }
        }
    }
}
